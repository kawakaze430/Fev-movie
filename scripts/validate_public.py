#!/usr/bin/env python3
"""Fail-closed checks for the only data and assets allowed in a public build."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import urlsplit, unquote
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
# Bundled decorative artwork can be added here only after its original source
# has been reviewed. Catalog poster assets are independently rights-gated below.
ORIGINAL_DECORATIVE_ASSETS: dict[str, str] = {
    'art/hero.svg': '163aff081f010f6d14ed86ecc4130744bb1f20ea10109baa61a91c1ddc0a9c21',
    'art/favicon.svg': '8646ffdf7102448080e47c69f626936f0088afc1452130619a02aa5c2d42a5b8',
}


class PublicDataError(ValueError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise PublicDataError(message)


def safe_url(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) <= 32 for c in value) or '\\' in value:
        return False
    try:
        p = urlsplit(value)
        host = p.hostname
        if p.scheme not in {'https', 'http'} or not host or p.username or p.password:
            return False
        host = host.rstrip('.').lower()
        if host in {'localhost', 'metadata.google.internal'} or host.endswith(('.localhost', '.local', '.internal')) or '.' not in host:
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            # Browsers interpret legacy short/octal/hex IPv4 representations.
            if all(re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)', part) for part in host.split('.')):
                return False
            host.encode('idna')
            return bool(re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host)) and '..' not in host and (p.port is None or 0 < p.port <= 65535)
    except (ValueError, UnicodeError):
        return False


def validate_svg(path: Path) -> None:
    """Original demo illustrations may use a small, inert SVG subset."""
    raw = path.read_bytes()
    check(len(raw) < 1_000_000, f'oversized SVG asset: {path.name}')
    check(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), f'active SVG declaration: {path.name}')
    allowed = {'svg', 'g', 'defs', 'linearGradient', 'radialGradient', 'stop', 'rect', 'path', 'circle', 'ellipse', 'line', 'polygon', 'polyline', 'text', 'tspan', 'clipPath', 'mask', 'filter', 'feGaussianBlur', 'feBlend', 'feColorMatrix', 'feOffset', 'feFlood', 'feComposite', 'feMerge', 'feMergeNode', 'feTurbulence', 'feComponentTransfer', 'feFuncA', 'pattern', 'title', 'desc'}
    try:
        tree = ET.fromstring(raw)
    except ET.ParseError as e:
        raise PublicDataError(f'invalid SVG: {path.name}') from e
    for element in tree.iter():
        check(element.tag.rsplit('}', 1)[-1] in allowed, f'active or unsupported SVG element: {path.name}')
        for name, value in element.attrib.items():
            short = name.rsplit('}', 1)[-1].lower()
            check(not short.startswith('on') and short not in {'href', 'src'}, f'active SVG attribute: {path.name}')
            check(not re.search(r'(?:javascript:|https?:|data:|@import|expression\s*\()', value, re.I), f'external SVG reference: {path.name}')
            for match in re.findall(r'url\((.*?)\)', value, re.I):
                check(match.strip(' \"\'').startswith('#'), f'external SVG URL: {path.name}')


def validate_catalog(catalog: Path, site: Path) -> int:
    from importer.validation import validate_public

    try:
        document = json.loads(catalog.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise PublicDataError(f'cannot read catalog: {catalog.name}') from e
    # Importer validation is the shared schema and rights policy. Additional
    # boundary checks below verify actual deployed files, rather than JSON alone.
    validate_public(document)
    movies = document['movies']
    seen: set[str] = set()
    referenced_assets: set[str] = set()
    for movie in movies:
        key = movie['id']
        check(key not in seen, 'duplicate public movie id')
        seen.add(key)
        check(movie['rights']['distribution'] == 'cleared', 'uncleared movie in public catalog')
        check(bool(movie['rights']['evidence'].strip()), 'missing distribution evidence')
        for link in movie['links']:
            check(safe_url(link['url']), 'unsafe public external link')
        poster = movie.get('poster')
        if poster is None:
            continue
        check(isinstance(poster, str), 'poster must be a local path')
        decoded = unquote(poster)
        relative = PurePosixPath(decoded.lstrip('/'))
        check(not decoded.startswith('//') and '\\' not in decoded and '?' not in decoded and '#' not in decoded and ':' not in decoded, 'unsafe poster path')
        check(relative.parts and relative.parts[0] in {'posters', 'art'} and '..' not in relative.parts, 'poster must live in posters/ or art/')
        target = site.joinpath(*relative.parts)
        referenced_assets.add(relative.as_posix())
        check(target.is_file() and not target.is_symlink(), 'missing or linked public poster asset')
        check(target.resolve().is_relative_to(site.resolve()), 'poster escapes site directory')
        extension = target.suffix.lower()
        if extension == '.svg':
            check(document['kind'] == 'demo' and movie['rights']['poster'] == 'original', 'SVG posters are only allowed for original demo artwork')
            validate_svg(target)
        else:
            check(extension in {'.png', '.jpg', '.jpeg', '.webp'}, 'unsupported poster format')
            check(movie['rights']['poster'] in {'original', 'licensed'}, 'poster has no rights clearance')
    for directory in ['posters', 'art']:
        for path in (site / directory).rglob('*'):
            if not path.is_file():
                continue
            relative_name = path.relative_to(site).as_posix()
            if relative_name in referenced_assets:
                continue
            expected_hash = ORIGINAL_DECORATIVE_ASSETS.get(relative_name)
            check(bool(expected_hash) and hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash, f'unreferenced or unapproved public artwork: {relative_name}')
    return len(movies)


def scan_site(site: Path, built: bool) -> None:
    check(site.is_dir(), f'missing site directory: {site.name}')
    allowed_root = {'index.html', 'robots.txt', 'favicon.svg', 'favicon.ico', 'site.webmanifest'}
    for path in site.rglob('*'):
        rel = path.relative_to(site)
        check(not path.is_symlink(), 'symlink in public site')
        if not path.is_file():
            continue
        parts = rel.parts
        name = path.name.lower()
        check(not any(p.startswith('.') for p in parts), 'hidden file in public site')
        check(not any(p.lower() in {'private', 'archives', 'exports', 'raw', 'reports', 'node_modules', 'importer', 'tests'} for p in parts), 'private directory in public site')
        if rel.as_posix() == 'data/movies.json':
            continue
        if parts[0] in {'posters', 'art'} and path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.svg'}:
            if path.suffix.lower() == '.svg':
                validate_svg(path)
            continue
        if len(parts) == 1 and name in allowed_root:
            if name == 'index.html':
                check(built, 'HTML export or entrypoint in public assets')
            if name == 'favicon.svg':
                validate_svg(path)
            continue
        if built and parts[0] == 'assets' and path.suffix.lower() in {'.js', '.css', '.woff', '.woff2', '.png', '.jpg', '.webp', '.svg'}:
            continue
        raise PublicDataError(f'unexpected file in public site: {rel.as_posix()}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, default=ROOT / 'public')
    parser.add_argument('--built', action='store_true', help='validate Vite dist instead of source public assets')
    args = parser.parse_args()
    try:
        scan_site(args.site, args.built)
        count = validate_catalog(args.site / 'data' / 'movies.json', args.site)
    except (PublicDataError, ValueError, KeyError, TypeError) as e:
        print(f'Public artifact check FAILED: {e}', file=sys.stderr)
        return 1
    print(f'Public artifact check passed: {count} cleared records; no private artifacts.')
    return 0


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
