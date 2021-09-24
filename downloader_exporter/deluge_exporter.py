import time
from urllib.parse import urlparse
from collections import Counter

from loguru import logger
from attrdict import AttrDict
from deluge_client import DelugeRPCClient, FailedToReconnectException
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily

from downloader_exporter.utils import url_parse
from downloader_exporter.constants import TorrentStatus, TorrentStat

DEFAULT_PORT = 58846


class DelugeMetricsCollector:
    def __init__(self, name: str, host: str, username: str, password: str, **kwargs):
        self.name = name
        self.host = host
        self.username = username
        self.password = password
        self.version = ""
        self.lt_version = ""

    def call(self, client, method, *args, **kwargs):
        try:
            return client.call(method, *args, **kwargs)
        except Exception as e:
            logger.error(
                f"[{self.name}] Cannot connect to deluge client {self.name}, method: {method}: {e}"
            )
        return ""

    @property
    def client(self):
        _, host, port = url_parse(self.host)
        return DelugeRPCClient(
            host=host,
            port=port,
            username=self.username,
            password=self.password,
            decode_utf8=True,
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
                    "lt_version": self.lt_version,
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
        with self.client as client:
            metrics.extend(self.get_status_metrics(client))
            metrics.extend(self.get_torrent_metrics(client))
        return metrics

    def get_status_metrics(self, client):
        self.version = self.call(client, "daemon.info")
        if self.version:
            self.version = self.version
        self.lt_version = self.call(client, "core.get_libtorrent_version")
        if self.lt_version:
            self.lt_version = self.lt_version
        status = self.call(
            client,
            "core.get_session_status",
            [
                "download_rate",
                "upload_rate",
                "total_download",
                "total_upload",
            ],
        )
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
                "value": status.get("total_download", 0),
                "help": "Data downloaded this session (bytes)",
                "type": "counter",
            },
            {
                "name": "downloader_download_speed_bytes",
                "value": status.get("download_rate", 0),
                "help": "Data download speed (bytes)",
            },
            {
                "name": "downloader_upload_bytes_total",
                "value": status.get("total_upload", 0),
                "help": "Data uploaded this session (bytes)",
                "type": "counter",
            },
            {
                "name": "downloader_upload_speed_bytes",
                "value": status.get("upload_rate", 0),
                "help": "Data upload speed (bytes)",
            },
        ]

    def get_torrent_metrics(self, client):
        torrents = self.call(
            client,
            "core.get_torrents_status",
            {},
            ["state", "label", "tracker", "total_uploaded", "name"],
        )
        if not torrents:
            return []
        counter = Counter()
        metrics = []
        for torrent_hash, val in torrents.items():
            tracker = urlparse(val.get("tracker", "https://unknown.tracker")).netloc
            counter[
                TorrentStat(
                    TorrentStatus.parse_de(val.get("state", "")).value,
                    val.get("label", "Uncategorized"),
                    tracker,
                )
            ] += 1
            torrent_name = val.get("name", "unknown")
            metrics.append(
                {
                    "name": "downloader_tracker_torrent_upload_bytes_total",
                    "type": "counter",
                    "value": val.get("total_uploaded", 0.0),
                    "labels": {
                        "torrent_name": torrent_name,
                        "tracker": tracker,
                    },
                    "help": f"Data uploaded to tracker {tracker} for torrent {torrent_name}",
                }
            )

        for t, count in counter.items():
            metrics.append(
                {
                    "name": "downloader_torrents_count",
                    "value": count,
                    "labels": {
                        "status": t.status,
                        "category": t.category,
                        "tracker": t.tracker,
                    },
                    "help": f"Number of torrents in status {t.status} under category {t.category} with tracker {t.tracker}",
                }
            )
        return metrics
