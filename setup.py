from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name='downloader-exporter',
    packages=['downloader_exporter'],
    version='0.3.7',
    long_description=long_description,
    long_description_content_type="text/markdown",
    description='Prometheus exporter for torrent downloader like qbittorrent/transmission/deluge',
    author='Lei Shi',
    author_email='me@leishi.io',
    url='https://github.com/leishi1313/downloader-exporter',
    download_url='https://github.com/leishi1313/downloader-exporter/archive/0.3.7.tar.gz',
    keywords=['prometheus', 'qbittorrent', 'transmission', 'deluge'],
    classifiers=[],
    python_requires='>=3.6.2',
    install_requires=[
        'attrdict==2.0.1',
        'deluge-client==1.9.0',
        'loguru==0.5.3',
        'qbittorrent-api==2021.8.23',
        'transmission-rpc==3.2.7',
        'prometheus_client==0.11.0',
        'pyyaml==5.4.1',
    ],
    entry_points={
        'console_scripts': [
            'downloader-exporter=downloader_exporter.exporter:main',
        ]
    }
)
