import time
from collections import Counter

from loguru import logger
from attrdict import AttrDict
from transmission_rpc import Client
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily

from downloader_exporter.utils import url_parse
from downloader_exporter.constants import TorrentStatus

DEFAULT_PORT = 9091


class TransmissionMetricsCollector:
    def __init__(
        self,
        name: str,
        host: str,
        username: str,
        password: str,
        timeout: int = 4,
        **kwargs,
    ):
        self.name = name
        self.host = host
        self.username = username
        self.password = password
        self.timeout = timeout
        self.version = None

    @property
    def client(self):
        scheme, host, port = url_parse(self.host, DEFAULT_PORT)
        return Client(
            host=host,
            port=port,
            username=self.username,
            password=self.password,
            protocol="https" if scheme == "https" or port == 443 else "http",
            timeout=self.timeout,
        )

    def describe(self):
        return [AttrDict({"name": self.name, "type": "info"})]

    def collect(self):
        metrics = self.get_metrics()

        for metric in metrics:
            name = metric["name"]
            value = metric["value"]
            help_text = metric.get("help", "")
            labels = {
                **metric.get("labels", {}),
                **{
                    "name": self.name,
                    "version": self.version,
                    "client": "deluge",
                    "host": self.host,
                },
            }
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
        try:
            session = self.client.session_stats()
            self.version = session.version
            stat = session.cumulative_stats
        except Exception as e:
            logger.error(f"Can not get client session: {e}")
            self.version = ""
            session = AttrDict()
            stat = {}

        return [
            {
                "name": "downloader_up",
                "value": self.version != "",
                "help": "Whether if server is alive or not",
            },
            {
                "name": "downloader_download_bytes_total",
                "value": stat.get("downloadedBytes", 0),
                "help": "Data downloaded this session (bytes)",
                "type": "counter",
            },
            {
                "name": "downloader_download_speed_bytes",
                "value": getattr(session, "downloadSpeed", 0),
                "help": "Data download speed (bytes)",
            },
            {
                "name": "downloader_upload_bytes_total",
                "value": stat.get("uploadedBytes", 0),
                "help": "Data uploaded this session (bytes)",
                "type": "counter",
            },
            {
                "name": "downloader_upload_speed_bytes",
                "value": getattr(session, "uploadSpeed", 0),
                "help": "Data upload speed (bytes)",
            },
        ]

    def get_torrent_metrics(self):
        try:
            torrents = self.client.get_torrents(
                arguments=["name", "status", "tracker", "isFinished", "isStalled"]
            )
        except Exception as e:
            logger.error(f"Can not get client torrents: {e}")
            torrents = []

        counter = Counter()
        for t in torrents:
            counter[TorrentStatus.parse_tr(t.status).value] += 1

        metrics = []
        for status, count in counter.items():
            metrics.append(
                {
                    "name": "downloader_torrents_count",
                    "value": count,
                    "labels": {
                        "status": status,
                        "category": "Uncategorized",
                        "tracker": "",
                    },
                    "help": f"Number of torrents in status {status}",
                }
            )
        return metrics
