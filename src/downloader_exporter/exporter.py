import time
import os
import sys
import signal
import argparse
import threading
import faulthandler
from wsgiref.simple_server import make_server, WSGIRequestHandler, WSGIServer

try:
    from urllib import quote_plus

    from BaseHTTPServer import BaseHTTPRequestHandler
    from SocketServer import ThreadingMixIn
    from urllib2 import (
        build_opener, HTTPError, HTTPHandler, HTTPRedirectHandler, Request,
    )
    from urlparse import parse_qs, urlparse
except ImportError:
    # Python 3
    from http.server import BaseHTTPRequestHandler
    from socketserver import ThreadingMixIn
    from urllib.error import HTTPError
    from urllib.parse import parse_qs, quote_plus, urlparse
    from urllib.request import (
        build_opener, HTTPHandler, HTTPRedirectHandler, Request,
    )

import yaml
from loguru import logger
from prometheus_client import start_http_server, Metric, generate_latest, CONTENT_TYPE_LATEST, make_wsgi_app as old_make_wsgi_app
from prometheus_client.core import REGISTRY, CollectorRegistry
from prometheus_client.openmetrics import exposition as openmetrics

from downloader_exporter.deluge_exporter import DelugeMetricsCollector
from downloader_exporter.qbittorrent_exporter import QbittorrentMetricsCollector
from downloader_exporter.transmission_exporter import TransmissionMetricsCollector

def restricted_registry(self, names):
    names = set(names)
    collectors = set()
    metrics = []
    with self._lock:
        if 'target_info' in names and self._target_info:
            metrics.append(self._target_info_metric())
            names.remove('target_info')
        for name in names:
            if name in self._names_to_collectors:
                collectors.add(self._names_to_collectors[name])
    for collector in collectors:
        for metric in collector.collect():
            metrics.append(metric)

    class RestrictedRegistry(object):
        def collect(self):
            return metrics

    return RestrictedRegistry()
        

# Monkey patch restricted_registry
CollectorRegistry.restricted_registry = restricted_registry

def choose_encoder(accept_header):
    accept_header = accept_header or ''
    for accepted in accept_header.split(','):
        if accepted.split(';')[0].strip() == 'application/openmetrics-text':
            return (openmetrics.generate_latest,
                    openmetrics.CONTENT_TYPE_LATEST)
    return generate_latest, CONTENT_TYPE_LATEST

def bake_output(registry, accept_header, params):
    """Bake output for metrics output."""
    encoder, content_type = choose_encoder(accept_header)
    if 'name' in params:
        registry = registry.restricted_registry(params['name'])
    output = encoder(registry)
    return str('200 OK'), (str('Content-Type'), content_type), output


def make_wsgi_app(registry=REGISTRY):
    """Create a WSGI app which serves the metrics from a registry."""
    def prometheus_app(environ, start_response):
        # Prepare parameters
        accept_header = environ.get('HTTP_ACCEPT')
        params = parse_qs(environ.get('QUERY_STRING', ''))
        if environ['PATH_INFO'] == '/favicon.ico':
            # Serve empty response for browsers
            status = '200 OK'
            header = ('', '')
            output = b''
        else:
            # Bake output
            status, header, output = bake_output(registry, accept_header, params)
        # Return output
        start_response(status, [header])
        return [output]

    return prometheus_app


class _SilentHandler(WSGIRequestHandler):
    """WSGI handler that does not log requests."""

    def log_message(self, format, *args):
        """Log nothing."""


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    """Thread per request HTTP server."""
    # Make worker threads "fire and forget". Beginning with Python 3.7 this
    # prevents a memory leak because ``ThreadingMixIn`` starts to gather all
    # non-daemon threads in a list in order to join on them at server close.
    daemon_threads = True


def start_wsgi_server(port, addr='', registry=REGISTRY):
    """Starts a WSGI server for prometheus metrics as a daemon thread."""
    app = make_wsgi_app(registry)
    httpd = make_server(addr, port, app, ThreadingWSGIServer, handler_class=_SilentHandler)
    t = threading.Thread(target=httpd.serve_forever)
    t.daemon = True
    t.start()

# Enable dumps on stderr in case of segfault
faulthandler.enable()

class SignalHandler():
    def __init__(self):
        self.shutdown = False

        # Register signal handler
        signal.signal(signal.SIGINT, self._on_signal_received)
        signal.signal(signal.SIGTERM, self._on_signal_received)

    def is_shutting_down(self):
        return self.shutdown

    def _on_signal_received(self, signal, frame):
        logger.info("Exporter is shutting down")
        self.shutdown = True


def main():
    parser = argparse.ArgumentParser(description='BT clients stats exporter.')
    parser.add_argument('-c', '--config', help='The path to config file', default='/config/config.yml')
    parser.add_argument('-p', '--port', type=int, help='The port to use', default=9000)
    parser.add_argument('--multi', action="store_true", help='Use different ports for each exporter')
    args = parser.parse_args()

    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)

    # Register signal handler
    signal_handler = SignalHandler()

    # Register our custom collector
    counter = 0
    logger.info("Exporter is starting up")
    for name, c in config.items():
        client = c.get('client')
        if client == 'qbittorrent':
            collector = QbittorrentMetricsCollector(name=name, **c)
        elif client == 'deluge':
            collector=DelugeMetricsCollector(name=name, **c)
        elif client == 'transmission':
            collector=TransmissionMetricsCollector(name=name, **c)
        else:
            logger.warning(f"Unsupported client: {client}, config: {c}")
            continue

        if args.multi:
            logger.info(f"Registering {name} at port {args.port+counter}")
            start_http_server(args.port+counter, registry=collector)
        else:
            logger.info(f"Registering {name}")
            REGISTRY.register(collector)
        counter += 1

    # Start server
    if not args.multi:
        start_wsgi_server(args.port, registry=REGISTRY)
        logger.info(f"Exporter listening on port {args.port}")

    while not signal_handler.is_shutting_down():
        time.sleep(1)

    logger.info("Exporter has shutdown")


if __name__ == '__main__':
    main()