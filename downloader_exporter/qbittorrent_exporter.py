from urllib.parse import urlparse
from collections import Counter, defaultdict

from loguru import logger
from attrdict import AttrDict
from qbittorrentapi import Client, TorrentStates
from qbittorrentapi.exceptions import APIConnectionError
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily

from downloader_exporter.constants import TorrentStatus, TorrentStat


class QbittorrentMetricsCollector:
    TORRENT_STATUSES = [
        "downloading",
        "uploading",
        "complete",
        "checking",
        "errored",
        "paused",
    ]

    def __init__(
        self,
        name: str,
        host: str,
        username: str,
        password: str,
        verify_ssl: bool = False,
        **kwargs,
    ):
        self.name = name
        self.host = host
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl

    def describe(self):
        return [AttrDict({"name": self.name, "type": "info"})]

    def collect(self):
        self.client = Client(
            host=self.host,
            username=self.username,
            password=self.password,
            VERIFY_WEBUI_CERTIFICATE=self.verify_ssl,
        )
        try:
            self.version = self.client.app.version
        except Exception as e:
            logger.error(f"Couldn't get server info: {e}")
            return []

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
                    "client": "qbittorrent",
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
        response = {}
        version = ""

        # Fetch data from API
        try:
            response = self.client.transfer.info
        except Exception as e:
            logger.error(f"Couldn't get server info: {e}")

        return [
            {
                "name": "downloader_up",
                "value": response.get("connection_status", "") == "connected",
                "help": "Whether if server is alive or not",
            },
            {
                "name": "downloader_download_bytes_total",
                "value": response.get("dl_info_data", 0),
                "help": "Data downloaded this session (bytes)",
                "type": "counter",
            },
            {
                "name": "downloader_download_speed_bytes",
                "value": response.get("dl_info_speed", 0),
                "help": "Data download speed (bytes)",
            },
            {
                "name": "downloader_upload_bytes_total",
                "value": response.get("up_info_data", 0),
                "help": "Data uploaded this session (bytes)",
                "type": "counter",
            },
            {
                "name": "downloader_upload_speed_bytes",
                "value": response.get("up_info_speed", 0),
                "help": "Data upload speed (bytes)",
            },
        ]

    def get_torrent_metrics(self):
        try:
            categories = self.client.torrent_categories.categories
            torrents = self.client.torrents.info()
        except Exception as e:
            logger.error(f"Couldn't fetch torrents: {e}")
            return []

        counter = Counter()
        tracker_counter = defaultdict(float)
        for torrent in torrents:
            counter[
                TorrentStat(
                    TorrentStatus.parse_qb(torrent["state"]).value,
                    torrent.get("category", "Uncategorized"),
                    urlparse(torrent.get("tracker", "")).netloc,
                )
            ] += 1
            tracker_counter[urlparse(torrent.get("tracker", "")).netloc] += torrent.get(
                "uploaded", 0.0
            )

        metrics = []
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
        for tracker, uploaded in tracker_counter.items():
            metrics.append(
                {
                    "name": "downloader_tracker_upload_bytes_total",
                    "type": "counter",
                    "value": uploaded,
                    "labels": {
                        "tracker": t.tracker,
                    },
                    "help": f"Data uploaded to tracker {tracker}",
                }
            )
        return metrics
