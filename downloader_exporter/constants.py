from enum import Enum


class TorrentStatus(enum):
    DOWNLOADING = 'downloading'
    UPLOADING   = 'uploading'
    COMPLETE    = 'completed'
    CHECKING    = 'checking'
    ERRORED     = 'errored'
    PAUSED      = 'paused'