import time
from collections import defaultdict

from loguru import logger
from attrdict import AttrDict
from deluge_client import DelugeRPCClient, FailedToReconnectException
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily

from downloader_exporter.utils import url_parse

DEFAULT_PORT = 58846

class DelugeMetricsCollector():

    def __init__(self, name: str, host: str, username: str, password: str, retry:int = 3, **kwargs):
        self.name = name
        self.host = host
        self.username = username
        self.password = password
        self.retry = retry
        self.version = ''
        self.lt_version = ''

    def call(self, method, *args, **kwargs):
        for _ in range(self.retry):
            try:
                return self.client.call(method, *args, **kwargs)
            except FailedToReconnectException as e:
                # 1 second delay between calls
                time.sleep(0.3)
        logger.error(f"Cannot connect to deluge client {self.name} after {self.retry} times.")
        return ''

    @property
    def client(self):
        _, host, port = url_parse(self.host)
        return DelugeRPCClient(
            host=host,
            port=port,
            username=self.username,
            password=self.password)

    def describe(self):
        return [AttrDict({'name': self.name, 'type': 'info'})]

    def collect(self):
        metrics = self.get_metrics()

        for metric in metrics:
            name = metric["name"]
            value = metric["value"]
            help_text = metric.get("help", "")
            labels = {**metric.get("labels", {}), **{"name": self.name, "version": self.version, "lt_version": self.lt_version, "client": "deluge", "host": self.host}}
            metric_type = metric.get("type", "gauge")

            if metric_type == "counter":
                prom_metric = CounterMetricFamily(name, help_text, labels=labels.keys())
            else:
                prom_metric = GaugeMetricFamily(name, help_text, labels=labels.keys())
            prom_metric.add_metric(value=value, labels=labels.values())
            yield prom_metric

    def get_metrics(self):
        metrics = []
        metrics.extend(self.get_status_metrics())
        metrics.extend(self.get_torrent_metrics())
        return metrics

    def get_status_metrics(self):
        self.version = self.call('daemon.get_version')
        if self.version:
            self.version = self.version.decode()
        self.lt_version = self.call('core.get_libtorrent_version')
        if self.lt_version:
            self.lt_version = self.lt_version.decode()
        status = self.call('core.get_session_status', [
            'download_rate',
            'upload_rate',
            'total_download',
            'total_upload',
        ])
        if not status:
            status = {}

        return [
            {
                "name": "downloader_up",
                "value": bool(status),
                "help": "Whether if server is alive or not",
            },
            {
                "name": "downloader_download_bytes_total",
                "value": status.get(b"total_download", 0),
                "help": "Data downloaded this session (bytes)",
                "type": "counter"
            },
            {
                "name": "downloader_download_speed_bytes",
                "value": status.get(b"download_rate", 0),
                "help": "Data download speed (bytes)",
            },
            {
                "name": "downloader_upload_bytes_total",
                "value": status.get(b"total_upload", 0),
                "help": "Data uploaded this session (bytes)",
                "type": "counter"
            },
            {
                "name": "downloader_upload_speed_bytes",
                "value": status.get(b"upload_rate", 0),
                "help": "Data upload speed (bytes)",
            }
        ]

    def get_torrent_metrics(self):
        torrents = self.call('core.get_torrents_status', {}, ['state', 'label'])
        if not torrents:
            torrents = {}
        counter = defaultdict(lambda: defaultdict(int))
        for val in torrents.values():
            label = val.get(b'label', b'').decode()
            if not label:
                label = 'Uncategorized'
            counter[label][val.get(b'state').decode()] += 1

        metrics = []
        for label in counter.keys():
            for state in counter[label].keys():
                metrics.append({
                    "name": "downloader_torrents_count",
                    "value": counter[label][state],
                    "labels": {
                        "status": state,
                        "category": label
                    },
                    "help": f"Number of torrents in status {state} under category {label}"
                })
        return metrics
