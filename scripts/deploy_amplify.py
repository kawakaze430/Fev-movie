#!/usr/bin/env python3
"""Deploy a reviewed public site ZIP to Amplify using an existing AWS CLI identity.

Standalone: Python 3.9+ and AWS CLI v2 are sufficient (for example AWS CloudShell).
No source build, Telegram export, credentials, or third-party Python module is read.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET
import zipfile

MAX_ZIP_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024
ORIGINAL_ART = {
    'art/hero.svg': '163aff081f010f6d14ed86ecc4130744bb1f20ea10109baa61a91c1ddc0a9c21',
    'art/favicon.svg': '8646ffdf7102448080e47c69f626936f0088afc1452130619a02aa5c2d42a5b8',
}


class DeploymentError(ValueError):
    pass


class AWSFailure(DeploymentError):
    def __init__(self, service: str, operation: str, code: str = 'CommandFailed'):
        self.code = code
        super().__init__(f'AWS {service} {operation} failed ({code}). Check the selected identity, region, and permissions.')


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DeploymentError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON field in public artifact.')
        result[key] = value
    return result


def text(value, limit=10000, nonempty=False):
    return isinstance(value, str) and len(value) <= limit and (not nonempty or bool(value.strip())) and not any(ord(c) < 32 and c not in '\n\t' for c in value)


def safe_external_url(value):
    if not text(value, 8192, True) or any(ord(c) <= 32 for c in value) or '\\' in value:
        return False
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').rstrip('.').lower()
        if parsed.scheme not in {'http', 'https'} or not host or parsed.username or parsed.password:
            return False
        if host in {'localhost', 'metadata.google.internal'} or host.endswith(('.localhost', '.local', '.internal', '.test', '.invalid')):
            return False
        if parsed.port is not None and parsed.port not in {80, 443}:
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            if '.' not in host or all(re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)', label) for label in host.split('.')):
                return False
            return all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.'))
    except ValueError:
        return False


def validate_svg(data: bytes) -> None:
    require(len(data) < 1_000_000 and b'<!DOCTYPE' not in data.upper() and b'<!ENTITY' not in data.upper(), 'Unsafe SVG declaration or size.')
    allowed = {'svg', 'g', 'defs', 'linearGradient', 'radialGradient', 'stop', 'rect', 'path', 'circle', 'ellipse', 'line', 'polygon', 'polyline', 'text', 'tspan', 'clipPath', 'mask', 'filter', 'feGaussianBlur', 'feBlend', 'feColorMatrix', 'feOffset', 'feFlood', 'feComposite', 'feMerge', 'feMergeNode', 'feTurbulence', 'feComponentTransfer', 'feFuncA', 'pattern', 'title', 'desc'}
    try:
        tree = ET.fromstring(data)
    except ET.ParseError as error:
        raise DeploymentError('Malformed SVG asset.') from error
    for element in tree.iter():
        require(element.tag.rsplit('}', 1)[-1] in allowed, 'Active SVG element in public artifact.')
        for key, value in element.attrib.items():
            name = key.rsplit('}', 1)[-1].lower()
            require(not name.startswith('on') and name not in {'href', 'src'}, 'Active SVG attribute in public artifact.')
            require(not re.search(r'(?:javascript:|https?:|data:|@import|expression\s*\()', value, re.I), 'External SVG reference in public artifact.')
            for reference in re.findall(r'url\((.*?)\)', value, re.I):
                require(reference.strip(' \"\'').startswith('#'), 'External SVG URL in public artifact.')


def validate_catalog(document: object, files: dict[str, bytes]) -> int:
    require(isinstance(document, dict) and set(document) == {'schemaVersion', 'generatedAt', 'kind', 'movies'}, 'Public catalog has unexpected or missing fields.')
    require(type(document['schemaVersion']) is int and document['schemaVersion'] == 1, 'Unsupported public catalog version.')
    require(document['kind'] in {'public', 'demo'}, 'Private catalogs cannot be deployed.')
    try:
        require(datetime.fromisoformat(document['generatedAt'].replace('Z', '+00:00')).tzinfo is not None, 'Catalog timestamp requires timezone.')
    except (AttributeError, TypeError, ValueError) as error:
        raise DeploymentError('Invalid public catalog timestamp.') from error
    require(isinstance(document['movies'], list), 'Public movies must be a list.')
    ids, referenced = set(), set()
    for movie in document['movies']:
        require(isinstance(movie, dict) and set(movie) == {'id', 'title', 'year', 'genres', 'synopsis', 'poster', 'links', 'sources', 'rights'}, 'Public record has unexpected or missing fields.')
        require(isinstance(movie['id'], str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', movie['id']) and movie['id'] not in ids, 'Invalid or duplicate public record ID.')
        ids.add(movie['id'])
        require(text(movie['title'], 500, True) and text(movie['synopsis']), 'Invalid public title or synopsis.')
        require(movie['year'] is None or type(movie['year']) is int and 1888 <= movie['year'] <= 2200, 'Invalid public year.')
        require(isinstance(movie['genres'], list) and all(text(value, 100, True) for value in movie['genres']), 'Invalid public genres.')
        require(len(set(movie['genres'])) == len(movie['genres']), 'Duplicate public genres.')
        rights = movie['rights']
        require(isinstance(rights, dict) and set(rights) == {'distribution', 'poster', 'evidence'}, 'Invalid public rights fields.')
        require(rights['distribution'] == 'cleared' and rights['poster'] in {'original', 'licensed', 'none'} and text(rights['evidence'], 5000, True), 'Missing explicit public content clearance.')
        require(isinstance(movie['links'], list), 'Invalid public links.')
        link_keys = set()
        for link in movie['links']:
            require(isinstance(link, dict) and set(link) == {'label', 'quality', 'url', 'size'}, 'Public link has private or missing fields.')
            require(text(link['label'], 500, True) and safe_external_url(link['url']), 'Unsafe public external link.')
            require(link['quality'] is None or text(link['quality'], 100, True), 'Invalid explicit public quality.')
            require(link['size'] is None or text(link['size'], 100, True), 'Invalid public file size.')
            identity = (link['url'], link['quality'], link['size'])
            require(identity not in link_keys, 'Duplicate public external link.')
            link_keys.add(identity)
        require(isinstance(movie['sources'], list), 'Invalid public sources.')
        for source in movie['sources']:
            require(isinstance(source, dict) and set(source) == {'channelId', 'channelName', 'messageId'} and all(text(value, 500, True) for value in source.values()), 'Private or invalid provenance in public catalog.')
        poster = movie['poster']
        if poster is None:
            require(rights['poster'] == 'none', 'Poster rights do not match absent asset.')
            continue
        require(isinstance(poster, str) and re.fullmatch(r'/posters/[A-Za-z0-9_-]+\.(?:svg|png|jpg|jpeg|webp)', poster), 'Unsafe public poster path.')
        name = poster[1:]
        require(name in files and rights['poster'] in {'original', 'licensed'}, 'Missing or uncleared public poster.')
        if name.endswith('.svg'):
            require(document['kind'] == 'demo' and rights['poster'] == 'original', 'Imported SVG poster is not permitted.')
            validate_svg(files[name])
        else:
            data = files[name]
            valid_image = (name.endswith('.png') and data.startswith(b'\x89PNG\r\n\x1a\n')) or (name.endswith(('.jpg', '.jpeg')) and data.startswith(b'\xff\xd8\xff')) or (name.endswith('.webp') and data.startswith(b'RIFF') and data[8:12] == b'WEBP')
            require(valid_image, 'Invalid public raster image signature.')
        referenced.add(name)
    for name, data in files.items():
        if name.startswith(('art/', 'posters/')) and name not in referenced:
            require(ORIGINAL_ART.get(name) == hashlib.sha256(data).hexdigest(), 'Unreferenced or unapproved public artwork.')
    return len(document['movies'])


def preflight(path: Path, expected_sha256: str | None = None, allow_demo: bool = False):
    require(path.is_file() and not path.is_symlink(), 'Public site ZIP does not exist or is a symlink.')
    require(0 < path.stat().st_size <= MAX_ZIP_BYTES, 'Public site ZIP exceeds the 100 MiB limit.')
    with path.open('rb') as source:
        payload = source.read(MAX_ZIP_BYTES + 1)
    require(len(payload) <= MAX_ZIP_BYTES, 'Public site ZIP exceeds the 100 MiB limit.')
    digest = hashlib.sha256(payload).hexdigest()
    require(expected_sha256 is None or re.fullmatch('[0-9a-fA-F]{64}', expected_sha256) and digest == expected_sha256.lower(), 'Public site ZIP SHA256 mismatch.')
    files, seen, total = {}, set(), 0
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            require(len(archive.infolist()) <= 10000, 'Too many public artifact entries.')
            for info in archive.infolist():
                name = info.filename
                relative = PurePosixPath(name)
                require(bool(name) and re.fullmatch(r'[A-Za-z0-9._/-]+', name) and not name.startswith('/') and relative.as_posix() == name.rstrip('/') and all(part not in {'.', '..'} and not part.startswith('.') for part in relative.parts), 'Unsafe public artifact path.')
                require(name.casefold() not in seen, 'Duplicate public artifact path.')
                seen.add(name.casefold())
                mode = stat.S_IFMT(info.external_attr >> 16)
                require(mode in {0, stat.S_IFREG, stat.S_IFDIR} and not info.flag_bits & 1, 'Linked, special, or encrypted public artifact entry.')
                if info.is_dir():
                    require(info.file_size == 0, 'Directory entry contains unexpected data.')
                    require(relative.parts[0] in {'assets', 'data', 'posters', 'art'}, 'Unexpected public artifact directory.')
                    continue
                require(info.file_size <= MAX_FILE_BYTES and info.file_size <= max(info.compress_size, 1) * 2000, 'Public artifact expansion limit exceeded.')
                total += info.file_size
                require(total <= MAX_TOTAL_BYTES, 'Public artifact expanded size exceeds 256 MiB.')
                allowed = name in {'index.html', 'data/movies.json', 'robots.txt', 'favicon.ico', 'favicon.svg', 'site.webmanifest'} or (len(relative.parts) == 2 and relative.parts[0] == 'assets' and relative.suffix.lower() in {'.js', '.css', '.woff', '.woff2', '.png', '.jpg', '.webp', '.svg'}) or (len(relative.parts) == 2 and relative.parts[0] in {'posters', 'art'} and relative.suffix.lower() in {'.svg', '.png', '.jpg', '.jpeg', '.webp'})
                require(allowed, 'Unexpected file in public site ZIP; private/source files are forbidden.')
                files[name] = archive.read(info)
    except (zipfile.BadZipFile, RuntimeError, OSError) as error:
        raise DeploymentError('Public site ZIP is unreadable or corrupt.') from error
    require('index.html' in files and 'data/movies.json' in files, 'ZIP must contain index.html and data/movies.json directly at its root.')
    require(b'<div id="root"' in files['index.html'] or b"<div id='root'" in files['index.html'], 'Public application mount element missing.')
    try:
        document = json.loads(files['data/movies.json'], object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as error:
        raise DeploymentError('Invalid public catalog JSON.') from error
    count = validate_catalog(document, files)
    require(count > 0, 'The public catalog has no cleared movie records to deploy.')
    require(document['kind'] != 'demo' or allow_demo, 'This ZIP contains fictional demo records, not Telegram history. Use a reviewed public catalog, or pass --allow-demo explicitly to deploy a labelled demo preview.')
    for name, data in files.items():
        if name.endswith('.svg'):
            validate_svg(data)
    return payload, files, digest, count


def aws(service: str, operation: str, region: str, *arguments):
    command = ['aws', service, operation, *arguments, '--region', region, '--output', 'json', '--no-cli-pager']
    process_environment = os.environ.copy()
    process_environment.update({'AWS_PAGER': '', 'AWS_CLI_AUTO_PROMPT': 'off'})
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, env=process_environment)
    except FileNotFoundError as error:
        raise DeploymentError('AWS CLI v2 is unavailable. Run this bundle in signed-in AWS CloudShell.') from error
    except subprocess.TimeoutExpired as error:
        raise AWSFailure(service, operation, 'Timeout') from error
    if result.returncode:
        match = re.search(r'An error occurred \(([A-Za-z0-9_.-]+)\)', result.stderr)
        raise AWSFailure(service, operation, match.group(1) if match else 'CommandFailed')
    try:
        return json.loads(result.stdout or '{}')
    except ValueError as error:
        raise AWSFailure(service, operation, 'InvalidResponse') from error


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise DeploymentError('HTTP redirect rejected; original HTTPS destination required.')


def upload_archive(url: str, payload: bytes) -> None:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower()
        s3_host = re.fullmatch(r'(?:[a-z0-9.-]+\.)?s3(?:[.-](?:dualstack\.)?[a-z]{2}(?:-gov)?-[a-z]+-[0-9]|-accelerate(?:\.dualstack)?)?\.amazonaws\.com(?:\.cn)?', host)
        require(parsed.scheme == 'https' and not parsed.username and not parsed.password and parsed.port in {None, 443} and bool(s3_host), 'AWS returned an unexpected upload destination.')
        request = Request(url, data=payload, method='PUT', headers={'Content-Type': 'application/zip'})
        with build_opener(NoRedirect()).open(request, timeout=60) as response:
            require(200 <= response.status < 300, 'Archive upload was not accepted.')
    except Exception:
        # HTTP exceptions and their string values can contain the presigned URL.
        raise DeploymentError('Public ZIP upload failed; deployment was not started. The signed upload URL was not logged.') from None


def poll_job(app_id: str, branch: str, job_id: str, region: str, timeout: int, interval: int = 15):
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        result = aws('amplify', 'get-job', region, '--app-id', app_id, '--branch-name', branch, '--job-id', job_id)
        status = result.get('job', {}).get('summary', {}).get('status')
        require(status in {'CREATED', 'PENDING', 'PROVISIONING', 'RUNNING', 'SUCCEED', 'FAILED', 'CANCELLING', 'CANCELLED'}, 'Unexpected Amplify job status.')
        if status != previous:
            print(f'Amplify job {job_id}: {status}')
            previous = status
        if status == 'SUCCEED':
            return
        require(status not in {'FAILED', 'CANCELLED'}, f'Amplify job {job_id} ended with {status}; app was retained for inspection.')
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(interval, remaining, 60))
    raise DeploymentError(f'Amplify job {job_id} did not finish before the timeout; app and job were retained. Inspect the job in the Amplify console.')


def verify_site(origin: str, files: dict[str, bytes]):
    opener = build_opener(NoRedirect())
    # Verify the printed visitor URL as well as the explicit index/asset paths.
    requests = [('', files['index.html'])] + list(files.items())
    for name, expected in requests:
        request = Request(origin + '/' + name, headers={'User-Agent': 'FrameReleaseVerification/1.0', 'Cache-Control': 'no-cache'})
        try:
            with opener.open(request, timeout=30) as response:
                require(response.status == 200, 'Public HTTPS artifact returned a non-200 response.')
                actual = response.read(len(expected) + 1)
                require(actual == expected, 'Deployed artifact differs from the reviewed ZIP.')
                if name in {'', 'index.html'}:
                    headers = response.headers
                    require(headers.get('X-Content-Type-Options') == 'nosniff', 'Deployed response is missing X-Content-Type-Options.')
                    require(headers.get('Referrer-Policy') == 'strict-origin-when-cross-origin', 'Deployed response is missing Referrer-Policy.')
                    require('max-age=' in headers.get('Strict-Transport-Security', ''), 'Deployed response is missing HSTS.')
                    csp = headers.get('Content-Security-Policy', '')
                    require(all(value in csp for value in ["default-src 'self'", "script-src 'self'", "object-src 'none'", "frame-ancestors 'none'"]), 'Deployed response is missing the expected CSP.')
        except DeploymentError:
            raise
        except Exception:
            raise DeploymentError('Public HTTPS verification failed. The app exists; inspect its Amplify job and retry verification.') from None


def deploy(args, payload: bytes, files: dict[str, bytes]) -> str:
    identity = aws('sts', 'get-caller-identity', args.region)
    require(isinstance(identity.get('Account'), str) and re.fullmatch(r'\d{12}', identity['Account']), 'AWS did not confirm the existing caller identity.')
    print('Existing AWS identity verified. No keys or login prompts are used.')
    headers_argument = 'file://' + str(args.headers.resolve())
    if args.app_id:
        app = aws('amplify', 'get-app', args.region, '--app-id', args.app_id).get('app', {})
        require(app.get('platform') == 'WEB' and not app.get('repository'), 'Existing app must be a manually deployed WEB app without a Git provider.')
        aws('amplify', 'update-app', args.region, '--app-id', args.app_id, '--custom-headers', headers_argument)
    else:
        app = aws('amplify', 'create-app', args.region, '--name', args.name, '--platform', 'WEB', '--custom-headers', headers_argument).get('app', {})
    app_id, domain = app.get('appId'), app.get('defaultDomain')
    require(isinstance(app_id, str) and re.fullmatch(r'[a-z0-9]{1,32}', app_id), 'AWS returned an invalid app ID.')
    require(args.app_id is None or args.app_id == app_id, 'AWS returned a different app ID from the requested app.')
    print(f'Amplify app: {app_id}; region: {args.region}; branch: {args.branch}')
    print(f'If a later step fails, reuse this app with --app-id {app_id}; no app or branch is deleted.')
    require(isinstance(domain, str) and re.fullmatch(r'[a-z0-9-]+\.amplifyapp\.com', domain), 'AWS returned an unexpected public domain.')
    try:
        aws('amplify', 'get-branch', args.region, '--app-id', app_id, '--branch-name', args.branch)
    except AWSFailure as error:
        if error.code != 'NotFoundException':
            raise
        aws('amplify', 'create-branch', args.region, '--app-id', app_id, '--branch-name', args.branch, '--stage', 'PRODUCTION')
    deployment = aws('amplify', 'create-deployment', args.region, '--app-id', app_id, '--branch-name', args.branch)
    job_id = deployment.get('jobId')
    require(isinstance(job_id, str) and re.fullmatch(r'[0-9A-Za-z_-]+', job_id), 'AWS returned an invalid deployment job ID.')
    upload_archive(deployment.get('zipUploadUrl', ''), payload)
    aws('amplify', 'start-deployment', args.region, '--app-id', app_id, '--branch-name', args.branch, '--job-id', job_id)
    poll_job(app_id, args.branch, job_id, args.region, args.timeout)
    origin = f'https://{args.branch}.{domain}'
    print(f'AWS reports deployment success: {origin}')
    for attempt in range(3):
        try:
            verify_site(origin, files)
            break
        except DeploymentError:
            if attempt == 2:
                raise
            print('Waiting for public HTTPS artifact/header propagation before verification retry.')
            time.sleep(10)
    print(f'Public HTTPS verified: {len(files)} files match the reviewed ZIP; security headers are present.')
    print(f'Website: {origin}')
    return origin


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-zip', type=Path, default=Path(__file__).with_name('site.zip'))
    bundled_headers = Path(__file__).with_name('customHttp.yml')
    default_headers = bundled_headers if bundled_headers.is_file() else Path(__file__).resolve().parents[1] / 'customHttp.yml'
    parser.add_argument('--headers', type=Path, default=default_headers)
    parser.add_argument('--region', default='ap-south-1')
    parser.add_argument('--name', default='frame-movie-catalog')
    parser.add_argument('--branch', default='main')
    parser.add_argument('--app-id', help='reuse an existing manual WEB app; never deletes existing resources')
    parser.add_argument('--expected-sha256', help='optional site ZIP digest from the release manifest')
    parser.add_argument('--timeout', type=int, default=900, help='deployment polling deadline in seconds (60–3600)')
    parser.add_argument('--dry-run', action='store_true', help='validate public ZIP and headers without requiring AWS CLI, credentials, or network')
    parser.add_argument('--allow-demo', action='store_true', help='explicitly permit the fictional demo preview; never treats it as imported history')
    args = parser.parse_args(argv)
    try:
        require(bool(re.fullmatch(r'[a-z]{2}(?:-gov)?-[a-z]+-[0-9]', args.region)), 'Invalid AWS region identifier.')
        require(bool(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', args.branch)), 'Branch must be a DNS-safe lowercase name.')
        require(text(args.name, 255, True) and '\n' not in args.name and '\t' not in args.name, 'Invalid Amplify app name.')
        require(args.app_id is None or re.fullmatch(r'[a-z0-9]{1,32}', args.app_id), 'Invalid app ID.')
        require(60 <= args.timeout <= 3600, 'Timeout must be between 60 and 3600 seconds.')
        payload, files, digest, count = preflight(args.site_zip, args.expected_sha256, args.allow_demo)
        require(args.headers.is_file() and args.headers.stat().st_size <= 25000, 'Missing or oversized customHttp.yml.')
        custom_headers = args.headers.read_text(encoding='utf-8')
        require(all(value in custom_headers for value in ['customHeaders:', 'Content-Security-Policy', "default-src 'self'", 'X-Content-Type-Options', 'Strict-Transport-Security']), 'customHttp.yml is missing required public response headers.')
        print(f'Public ZIP validated: {count} cleared records; {len(files)} files; SHA256 {digest}')
        if args.dry_run:
            print('Dry run complete: no AWS commands, network requests, or resource changes.')
            return 0
        deploy(args, payload, files)
        return 0
    except (DeploymentError, OSError, UnicodeError) as error:
        print(f'Deployment stopped: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
