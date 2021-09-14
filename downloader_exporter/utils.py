from urllib.parse import urlparse


def url_parse(url: str, default_port: int = None) -> (str, str, int):
    scheme = ''
    port = ''
    if url.startswith('http'):
        parsed = urlparse(url)
        scheme = parsed.scheme
        url = parsed.netloc

    splits = url.split(':')
    host = splits[0] if len(splits) > 0 else ''
    if len(splits) > 1 and splits[1].isdigit():
        port = int(splits[1])
    elif scheme == 'https':
        port = 443
    elif default_port is not None:
        port = default_port

    return (scheme, host, port)
