#!/usr/bin/env python3
"""Read-only verification of an explicitly supplied deployed HTTPS site."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit, urljoin
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.validate_public import safe_url


def get(url: str):
    request = Request(url, headers={'User-Agent': 'FrameReleaseVerification/1.0'})
    with urlopen(request, timeout=25) as response:
        if response.status != 200:
            raise ValueError('non-200 response')
        if urlsplit(response.url).scheme != 'https':
            raise ValueError('deployment redirected away from HTTPS')
        content = response.read(10_000_001)
        if len(content) > 10_000_000:
            raise ValueError('oversized response')
        return content, response.headers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', help='actual Amplify HTTPS origin')
    args = parser.parse_args()
    try:
        parsed = urlsplit(args.url)
        if parsed.scheme != 'https' or not safe_url(args.url) or parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
            raise ValueError('supply a public HTTPS origin without a path, query, or credentials')
        base = args.url.rstrip('/') + '/'
        page, headers = get(base)
        if b'<div id="root"' not in page and b"<div id='root'" not in page:
            raise ValueError('application mount element missing')
        expected_headers = {'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'strict-origin-when-cross-origin'}
        for name, expected in expected_headers.items():
            if headers.get(name) != expected:
                raise ValueError(f'missing expected response header: {name}')
        csp = headers.get('Content-Security-Policy', '')
        for policy in ["default-src 'self'", "object-src 'none'", "frame-ancestors 'none'"]:
            if policy not in csp:
                raise ValueError(f'missing expected CSP directive: {policy}')
        if 'max-age=' not in headers.get('Strict-Transport-Security', ''):
            raise ValueError('missing HSTS response header')
        data, _ = get(urljoin(base, 'data/movies.json'))
        document = json.loads(data)
        from importer.validation import validate_public
        validate_public(document)
        local = json.loads((Path(__file__).resolve().parents[1] / 'public/data/movies.json').read_text())
        if document != local:
            raise ValueError('deployed catalog differs from local release catalog')
        for poster in sorted({movie['poster'] for movie in document['movies'] if movie.get('poster')}):
            if not poster.startswith(('/posters/', '/art/')) or '..' in poster or '\\' in poster:
                raise ValueError('unsafe deployed poster path')
            image, image_headers = get(urljoin(base, poster.lstrip('/')))
            if not image or not image_headers.get('Content-Type', '').startswith('image/'):
                raise ValueError('deployed poster failed image response check')
        print(f'External deployment checks passed: HTTPS, security headers, catalog parity, and {len(document["movies"])} cleared records with reachable posters.')
        print('Run the browser suite against this URL to verify interactions and rendering.')
        return 0
    except Exception as e:
        print(f'External deployment verification FAILED: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
