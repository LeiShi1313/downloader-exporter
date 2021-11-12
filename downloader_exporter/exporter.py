import time
import os
import sys
import signal
import argparse
import faulthandler

import yaml
from loguru import logger
from attrdict import AttrDict
from prometheus_client import start_http_server, Metric
from prometheus_client.core import REGISTRY, CollectorRegistry

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
        start_http_server(args.port, registry=REGISTRY)
        logger.info(f"Exporter listening on port {args.port}")

    while not signal_handler.is_shutting_down():
        time.sleep(1)

    logger.info("Exporter has shutdown")


if __name__ == '__main__':
    main()