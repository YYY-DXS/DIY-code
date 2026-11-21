"""Environment and connectivity probe for the TTS route.

Writes one JSON file describing the proxy/certificate environment, TCP reachability
and an HTTPS request to the speech endpoint. Run it from a tool shell and from the
plugin's managed subprocess, then diff the two files.
"""

import argparse
import json
import os
import socket
import ssl
import urllib.request

KEYS = ('proxy', 'ssl', 'cert', 'path', 'temp', 'python', 'node', 'home', 'userprofile')


def environment():
    picked = {}
    for key, value in os.environ.items():
        if any(part in key.lower() for part in KEYS):
            picked[key] = value
    return picked


def tcp(host, port=443, timeout=6):
    try:
        with socket.create_connection((host, port), timeout):
            return 'ok'
    except Exception as error:  # noqa: BLE001 - probe reports the failure text
        return f'fail: {error}'


def https(url, timeout=8):
    try:
        context = ssl.create_default_context()
        with urllib.request.urlopen(url, timeout=timeout, context=context) as response:
            return f'http {response.status}'
    except Exception as error:  # noqa: BLE001 - probe reports the failure text
        return f'fail: {error}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--label', default='probe')
    args = parser.parse_args()

    report = {
        'label': args.label,
        'python': sys_version(),
        'env': environment(),
        'tcp_pypi': tcp('pypi.org'),
        'tcp_speech': tcp('speech.platform.bing.com'),
        'https_pypi': https('https://pypi.org/simple/'),
        'https_speech': https('https://speech.platform.bing.com/'),
    }
    with open(args.out, 'w', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    return 0


def sys_version():
    import sys

    return sys.version.split()[0]


if __name__ == '__main__':
    raise SystemExit(main())
