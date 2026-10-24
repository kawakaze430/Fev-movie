"""Import inert Telegram HTML exports without executing attached content.

All source material and analysis stay in an explicit private directory outside
this checkout. The publication command is a separate allowlist-based operation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import ipaddress
import tempfile
import unicodedata
from urllib.parse import unquote, urlsplit
import zipfile


class CatalogError(ValueError):
    """Actionable import, integrity, or publication failure."""


@dataclass(frozen=True)
class Limits:
    max_files: int = 100_000
    max_total_bytes: int = 12 * 1024**3
    max_file_bytes: int = 512 * 1024**2
    max_ratio: float = 250


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def digest_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _json_write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.catalog-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path) -> object:
    try:
        with path.open(encoding='utf-8') as source:
            return json.load(source)
    except (OSError, ValueError) as exc:
        raise CatalogError(f'Cannot read valid JSON: {path.name}: {exc}') from exc


def private_path(path: Path) -> Path:
    path = path.expanduser().resolve()
    repo = Path(__file__).resolve().parent.parent
    if path == repo or repo in path.parents or path in repo.parents:
        raise CatalogError('Private storage must be outside the Git checkout and must not contain it.')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _member_name(name: str) -> str:
    if '\x00' in name or '\\' in name or ':' in name:
        raise CatalogError('ZIP contains an unsafe platform-dependent path.')
    name = name.rstrip('/')
    parts = name.split('/')
    if not name or name.startswith('/') or any(p in ('', '.', '..') for p in parts):
        raise CatalogError('ZIP contains an unsafe archive path.')
    return PurePosixPath(*parts).as_posix()


def safe_extract(archive: Path, dest: Path, limits: Limits = Limits()) -> list[dict]:
    """Preflight a ZIP and extract regular files only with bounded streaming.

    Output includes every archive entry, including directories, in deterministic
    order. No caller supplied destination is reused or overwritten.
    """
    archive, dest = Path(archive), Path(dest)
    if dest.exists() or dest.is_symlink():
        raise CatalogError('Extraction destination already exists; refusing to overwrite.')
    try:
        with zipfile.ZipFile(archive) as source:
            entries = source.infolist()
            if len(entries) > limits.max_files:
                raise CatalogError('ZIP exceeds file-count quota.')
            seen: dict[str, str] = {}
            names: list[tuple[zipfile.ZipInfo, str]] = []
            total = 0
            spellings = {}
            for entry in entries:
                name = _member_name(entry.filename)
                normalized_name = unicodedata.normalize('NFKC', name)
                components = name.split('/')
                for index in range(1, len(components) + 1):
                    prefix = '/'.join(components[:index])
                    folded = unicodedata.normalize('NFKC', prefix).casefold()
                    if folded in spellings and spellings[folded] != prefix:
                        raise CatalogError('ZIP has case/Unicode-colliding parent paths.')
                    spellings[folded] = prefix
                key = normalized_name.casefold()
                if key in seen:
                    raise CatalogError('ZIP contains duplicate or case/Unicode-colliding paths.')
                seen[key] = 'directory' if entry.is_dir() else 'file'
                mode = entry.external_attr >> 16
                kind = stat.S_IFMT(mode)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise CatalogError('ZIP contains a symlink or unsupported special file.')
                if entry.flag_bits & 1:
                    raise CatalogError('Encrypted ZIP entries are not supported.')
                if entry.file_size > limits.max_file_bytes:
                    raise CatalogError('ZIP entry exceeds per-file size quota.')
                total += entry.file_size
                if total > limits.max_total_bytes:
                    raise CatalogError('ZIP exceeds total expansion quota.')
                if entry.file_size / max(1, entry.compress_size) > limits.max_ratio:
                    raise CatalogError('ZIP exceeds compression-ratio quota.')
                names.append((entry, name))
            for key in seen:
                parent = PurePosixPath(key).parent
                while str(parent) != '.':
                    if seen.get(str(parent)) == 'file':
                        raise CatalogError('ZIP has a file/directory path collision.')
                    parent = parent.parent
            dest.mkdir(parents=True, mode=0o700)
            inventory = []
            actual_total = 0
            try:
                for entry, name in sorted(names, key=lambda pair: pair[1]):
                    target = dest.joinpath(*PurePosixPath(name).parts)
                    if entry.is_dir():
                        target.mkdir(parents=True, exist_ok=True, mode=0o700)
                        inventory.append({'path': name, 'kind': 'directory', 'size': 0, 'sha256': None})
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    hash_value, written = hashlib.sha256(), 0
                    with source.open(entry) as incoming, target.open('xb') as outgoing:
                        os.chmod(target, 0o600)
                        for block in iter(lambda: incoming.read(1024 * 1024), b''):
                            written += len(block)
                            actual_total += len(block)
                            if written > limits.max_file_bytes or actual_total > limits.max_total_bytes:
                                raise CatalogError('ZIP streaming expansion exceeds quota.')
                            outgoing.write(block)
                            hash_value.update(block)
                    if written != entry.file_size:
                        raise CatalogError('ZIP declared and extracted file sizes disagree.')
                    inventory.append({'path': name, 'kind': 'file', 'size': written, 'sha256': hash_value.hexdigest()})
                return inventory
            except Exception:
                shutil.rmtree(dest)
                raise
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as exc:
        raise CatalogError(f'ZIP extraction failed: {exc}') from exc


@dataclass
class Node:
    tag: str
    attrs: dict
    children: list
    parent: 'Node | None' = None

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def has(self, cls: str) -> bool:
        return cls in self.attrs.get('class', '').split()

    def text(self) -> str:
        if self.tag in ('script', 'style'):
            return ''
        result = ''
        for child in self.children:
            result += child.text() if isinstance(child, Node) else child
            if isinstance(child, Node) and child.tag in ('br', 'div', 'p', 'li', 'h1', 'h2', 'tr'):
                result += '\n'
        return result


class TelegramHTML(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('root', {}, [])
        self.current = self.root
        self.depth = 0
        self.count = 0

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > 2_000_000 or self.depth > 128:
            raise CatalogError('HTML exceeds node-count or nesting quota.')
        node = Node(tag, dict(attrs), [], self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node
            self.depth += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current
        while node.parent is not None:
            if node.tag == tag:
                self.current = node.parent
                self.depth = sum(1 for _ in _ancestors(self.current))
                return
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


QUALITY = re.compile(r'(?<!\w)(2160p|1440p|1080p|720p|576p|480p|360p|240p|8K|4K|UHD|FHD|HD)(?!\w)', re.I)
SIZE = re.compile(r'(?<!\w)\d+(?:[.,]\d+)?\s*(?:GiB|MiB|KiB|GB|MB|KB|TB)(?!\w)', re.I)
YEAR = re.compile(r'(?<!\d)((?:18|19|20|21|22)\d{2})(?!\d)')
URL = re.compile(r'https?://[^\s<>"\u200b]+', re.I)
TITLE_LABEL = re.compile(r'^(?:movie\s*(?:name|title)?|film\s*(?:name|title)?|title|name)\s*[:=\-]\s*(.+)$', re.I)


def unique(values):
    return list(dict.fromkeys(values))


def safe_url(value: str) -> str | None:
    if not isinstance(value, str) or value != value.strip() or '\\' in value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            return None
        if len(value) > 8192 or any(ord(c) <= 32 for c in value):
            return None
        host = parsed.hostname.lower().rstrip('.')
        if host in ('localhost', 'metadata.google.internal') or '.' not in host or host.endswith(('.local', '.internal', '.localhost', '.test', '.invalid')):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if all(re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)', part) for part in host.split('.')):
                return None
            if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) or '..' in host:
                return None
        if parsed.port is not None and parsed.port not in (80, 443):
            return None
        return value
    except ValueError:
        return None


def parse_metadata(text: str) -> dict:
    """Extract only text evidence; quality is never inferred from file size."""
    lines = [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines() if line.strip()]
    cleaned = [re.sub(r'^[^\w\[(]+', '', line).strip() for line in lines]
    issues: list[str] = []
    titles = [match.group(1).strip() for line in cleaned if (match := TITLE_LABEL.match(line))]
    title = titles[0] if titles else None
    if len(set(titles)) > 1:
        title = None
        issues.append('ambiguous_title')
    if not title:
        candidates = [line for line in cleaned if not URL.search(line) and not re.match(r'^(?:genre|year|release|language|size|quality|download|rating|duration|audio|subtitle|country|director|cast|plot|synopsis|\d+\s*[MG]B)\b', line, re.I) and not SIZE.fullmatch(line) and not QUALITY.fullmatch(line) and not line.startswith(('#', '@'))]
        if candidates and not titles:
            title = candidates[0]
            issues.append('unlabelled_title')
    year_evidence = []
    for line in cleaned:
        if re.match(r'^(?:year|release(?:\s*(?:year|date))?)\s*[:=\-]', line, re.I):
            year_evidence.extend(YEAR.findall(line))
    if title:
        year_evidence.extend(re.findall(r'[\[(]\s*((?:18|19|20|21|22)\d{2})\s*[\])]', title))
    years = unique(int(year) for year in year_evidence)
    year = years[0] if len(years) == 1 and 1888 <= years[0] <= 2200 else None
    if any(not 1888 <= item <= 2200 for item in years):
        issues.append('invalid_year')
    if len(years) > 1:
        issues.append('ambiguous_year')
    if title:
        title = re.sub(r'\s*[\[(](?:18|19|20|21|22)\d{2}[\])]\s*', ' ', title)
        title = re.sub(r'\.(?:mkv|mp4|avi|mov)$', '', title, flags=re.I).strip(' \t-|')
        title = re.sub(r'\s+', ' ', title)
        if len(title) > 500:
            issues.append('title_truncated')
            title = title[:500]
    genres = []
    for line in cleaned:
        match = re.match(r'^genres?\s*[:=\-]\s*(.+)', line, re.I)
        if match:
            genres.extend(part.strip(' #') for part in re.split(r'[,/|;]|\s+#', match.group(1)) if part.strip(' #'))
    if any(len(genre) > 100 for genre in genres):
        issues.append('invalid_genre_length')
        genres = [genre for genre in genres if len(genre) <= 100]
    synopsis = ''
    for line in cleaned:
        match = re.match(r'^(?:plot|synopsis|description)\s*[:=\-]\s*(.+)', line, re.I)
        if match:
            synopsis = match.group(1)[:10000]
            if len(match.group(1)) > 10000:
                issues.append('synopsis_truncated')
    qualities = unique(match.group(0).upper() if match.group(0).lower() in ('hd', 'fhd', 'uhd', '4k', '8k') else match.group(0).lower() for match in QUALITY.finditer(text))
    sizes = unique(re.sub(r'\s+', ' ', match.group(0)) for match in SIZE.finditer(text))
    for field, value in [('title', title), ('year', year), ('genres', genres)]:
        if not value:
            issues.append('missing_' + field)
    return {'title': title, 'year': year, 'genres': unique(genres), 'synopsis': synopsis, 'sizes': sizes, 'qualities': qualities, 'issues': unique(issues)}


def _local_asset(value: str, page: Path, root: Path) -> str | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc:
            return None
        target = (page.parent / unquote(parsed.path)).resolve()
        target.relative_to(root.resolve())
        if target.is_file() and target.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
            return target.relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        pass
    return None


def parse_page(path: Path, root: Path, channel_id: str, channel_name: str) -> list[dict]:
    path, root = Path(path), Path(root)
    parser = TelegramHTML()
    try:
        parser.feed(path.read_text(encoding='utf-8-sig', errors='replace'))
    except (OSError, RecursionError) as exc:
        raise CatalogError(f'Cannot parse message page {path.name}: {exc}') from exc
    messages = []
    for node in parser.root.walk():
        if not node.has('message'):
            continue
        identifier = node.attrs.get('id')
        if not identifier:
            identifier = 'anonymous-' + str(len(messages) + 1)
        texts = [child for child in node.walk() if child.has('text')]
        text = '\n'.join(child.text().strip() for child in texts).strip()
        if not texts and node.has('service'):
            text = node.text().strip()
        posters, missing_assets, links, rejected_urls, attachments = [], [], [], [], []
        for child in node.walk():
            if child.tag == 'a' and (child.has('media_file') or child.has('media') and any(part.has('title') for part in child.walk()) or child.has('media_wrap') and any(part.has('media_file') for part in child.walk())):
                names = [part.text().strip() for part in child.walk() if part.has('title')]
                statuses = [part.text().strip() for part in child.walk() if part.has('status')]
                href = child.attrs.get('href', '')
                local = None
                try:
                    parsed = urlsplit(href)
                    if not parsed.scheme and not parsed.netloc:
                        candidate = (path.parent / unquote(parsed.path)).resolve()
                        candidate.relative_to(root.resolve())
                        if candidate.is_file():
                            local = candidate.relative_to(root.resolve()).as_posix()
                except (ValueError, OSError):
                    pass
                evidence = parse_metadata('\n'.join(names + statuses))
                attachments.append({'name': names[0] if names else '', 'path': local, 'sourcePath': href, 'status': ' '.join(statuses), 'sizes': evidence['sizes'], 'qualities': evidence['qualities'], 'exists': local is not None})
            if child.tag == 'a' and (child.has('photo_wrap') or child.has('photo')):
                value = child.attrs.get('href', '')
                asset = _local_asset(value, path, root)
                if asset:
                    posters.append(asset)
                elif value:
                    missing_assets.append(value)
            elif child.tag == 'img' and child.has('photo') and not any(n.has('photo_wrap') for n in _ancestors(child)):
                value = child.attrs.get('src', '')
                asset = _local_asset(value, path, root)
                if asset:
                    posters.append(asset)
                elif value:
                    missing_assets.append(value)
            if child.tag != 'a':
                continue
            url = child.attrs.get('href', '')
            if not re.match(r'^https?://', url, re.I):
                continue
            if not safe_url(url):
                rejected_urls.append(url)
                continue
            label = re.sub(r'\s+', ' ', child.text()).strip()
            metadata = parse_metadata(label)
            # A link may inherit a single explicit quality from its own line,
            # but never from neighbouring links or from a numeric file size.
            line = _anchor_context(child)
            context = parse_metadata(line)
            q = metadata['qualities'] or context['qualities']
            s = metadata['sizes'] or context['sizes']
            links.append({'url': url, 'label': label[:500] or 'External source', 'quality': q[0] if len(q) == 1 else None, 'size': s[0] if len(s) == 1 else None})
        known = {link['url'] for link in links}
        for match in URL.finditer(text):
            url = match.group(0).rstrip('.,);]')
            if url in known:
                continue
            if safe_url(url):
                links.append({'url': url, 'label': 'External source', 'quality': None, 'size': None})
                known.add(url)
            else:
                rejected_urls.append(url)
        metadata = parse_metadata(text)
        metadata['sizes'] = unique(metadata['sizes'] + [size for attachment in attachments for size in attachment['sizes']])
        metadata['qualities'] = unique(metadata['qualities'] + [quality for attachment in attachments for quality in attachment['qualities']])
        # Single quality/size in the entire caption is unambiguous only for a
        # single link. Multiple links keep unknown fields until reviewed.
        if len(links) == 1:
            if links[0]['quality'] is None and len(metadata['qualities']) == 1 and len(attachments) <= 1:
                links[0]['quality'] = metadata['qualities'][0]
            if links[0]['size'] is None and len(metadata['sizes']) == 1 and len(attachments) <= 1:
                links[0]['size'] = metadata['sizes'][0]
        issues = list(metadata['issues'])
        if attachments and not text:
            issues.append('attachment_without_caption')
        if any(not attachment['exists'] for attachment in attachments):
            issues.append('missing_attachment_asset')
        if len(metadata['qualities']) > 1 and len(links) == 1:
            issues.append('ambiguous_link_quality')
        if len(metadata['sizes']) > 1 and len(links) == 1:
            issues.append('ambiguous_link_size')
        if missing_assets:
            issues.append('missing_poster_asset')
        if rejected_urls:
            issues.append('unsafe_external_url')
        candidate_posters = []
        if node.has('joined') and not posters and messages and messages[-1]['posters']:
            issues.append('ambiguous_adjacent_poster')
            candidate_posters = [{'messageId': messages[-1]['id'], 'posters': list(messages[-1]['posters'])}]
        if links and any(link['quality'] is None for link in links):
            issues.append('missing_link_quality')
        if links and any(link['size'] is None for link in links):
            issues.append('missing_link_size')
        if not metadata['sizes']:
            issues.append('missing_file_size')
        messages.append({'id': identifier, 'page': path.relative_to(root).as_posix(), 'channelId': channel_id, 'channelName': channel_name, 'kind': 'service' if node.has('service') else 'message', 'text': text, 'posters': unique(posters), 'missingAssets': unique(missing_assets), 'attachments': attachments, 'urls': links, 'rejectedUrls': unique(rejected_urls), 'metadata': metadata, 'joined': node.has('joined'), 'candidatePosters': candidate_posters, 'issues': unique(issues)})
    return messages


def _ancestors(node):
    node = node.parent
    while node is not None:
        yield node
        node = node.parent



def _anchor_context(anchor: Node) -> str:
    """Render a link's own caption line by node identity, never label matching."""
    container = next((node for node in _ancestors(anchor) if node.has('text')), None)
    if container is None:
        return ''
    marker = '\x00CATALOG_ANCHOR\x00'
    def render(node):
        if isinstance(node, str):
            return node
        if node.tag in ('script', 'style'):
            return ''
        result = marker if node is anchor else ('\x00OTHER_ANCHOR\x00' if node.tag == 'a' else '')
        for child in node.children:
            result += render(child)
            if isinstance(child, Node) and child.tag in ('br', 'div', 'p', 'li', 'tr'):
                result += '\n'
        return result
    lines = [line for line in render(container).splitlines() if marker in line]
    return lines[0].replace(marker, '') if len(lines) == 1 and '\x00OTHER_ANCHOR\x00' not in lines[0] else ''


def normalize_title(title: str) -> str:
    title = unicodedata.normalize('NFKC', title).casefold()
    return re.sub(r'[^\w]+', ' ', title).strip()


def merge_movies(messages: list[dict], channel_id: str = '', channel_name: str = '') -> tuple[list[dict], list[dict]]:
    """Conservative, deterministic dedup across channels with source provenance."""
    merged: dict[str, dict] = {}
    issues: list[dict] = []
    unknown_titles: dict[str, list[str]] = {}
    for message in messages:
        meta = message.get('metadata') or parse_metadata(message.get('text', ''))
        if message.get('kind') == 'service':
            continue
        source = {'channelId': message.get('channelId', channel_id), 'channelName': message.get('channelName', channel_name), 'messageId': message['id'], 'page': message.get('page', '')}
        if not meta['title']:
            issues.append({'code': 'message_not_catalogued', 'source': source, 'fields': message.get('issues', meta['issues'])})
            issues.extend({'code': code, 'source': source} for code in message.get('issues', meta['issues']))
            continue
        normalized = normalize_title(meta['title'])
        key = f"title:{normalized}|year:{meta['year']}"
        if meta['year'] is None:
            # Missing years do not collapse remakes or merge unrelated channels.
            key += f"|source:{source['channelId']}:{source['page']}:{source['messageId']}"
            unknown_titles.setdefault(normalized, []).append(key)
        identifier = hashlib.sha256(key.encode()).hexdigest()[:24]
        movie = merged.get(key)
        poster_paths = message.get('posterPaths', message.get('posters', []))
        if movie is None:
            movie = {'id': identifier, 'title': meta['title'], 'year': meta['year'], 'genres': list(meta['genres']), 'synopsis': meta.get('synopsis', ''), 'posters': list(poster_paths), 'links': [], 'sources': [], 'issues': []}
            merged[key] = movie
        else:
            if movie['genres'] and meta['genres'] and set(movie['genres']) != set(meta['genres']):
                issues.append({'code': 'conflicting_genres', 'movieId': identifier, 'source': source})
                movie['issues'].append('conflicting_genres')
            if movie['synopsis'] and meta.get('synopsis') and movie['synopsis'] != meta['synopsis']:
                issues.append({'code': 'conflicting_synopsis', 'movieId': identifier, 'source': source})
            movie['genres'] = unique(movie['genres'] + meta['genres'])
            movie['posters'] = unique(movie['posters'] + poster_paths)
            movie['synopsis'] = movie['synopsis'] or meta.get('synopsis', '')
        if source not in movie['sources']:
            movie['sources'].append(source)
        for link in message.get('urls', message.get('links', [])):
            existing = next((old for old in movie['links'] if (old['url'], old['quality'], old['size']) == (link['url'], link['quality'], link['size'])), None)
            if existing is None:
                movie['links'].append(link)
            elif existing['label'] != link['label']:
                issues.append({'code': 'conflicting_link_labels', 'movieId': identifier, 'source': source})
        movie['issues'] = unique(movie['issues'] + message.get('issues', meta['issues']))
        for code in message.get('issues', meta['issues']):
            issues.append({'code': code, 'movieId': identifier, 'source': source})
    for ids in unknown_titles.values():
        if len(ids) > 1:
            issues.append({'code': 'possible_duplicates_missing_year', 'movieIds': [merged[key]['id'] for key in ids]})
    movies = sorted(merged.values(), key=lambda movie: (movie['title'].casefold(), movie['year'] or 0, movie['id']))
    for movie in movies:
        if not movie['posters']:
            movie['issues'] = unique(movie['issues'] + ['missing_poster'])
            issues.append({'code': 'missing_poster', 'movieId': movie['id']})
        if not movie['links']:
            movie['issues'] = unique(movie['issues'] + ['missing_external_links'])
            issues.append({'code': 'missing_external_links', 'movieId': movie['id']})
    return movies, issues


def validate_catalog(catalog: dict, public: bool = False) -> None:
    """Strict shape and semantic validation independent of a JSON Schema engine."""
    def require(condition, message):
        if not condition:
            raise CatalogError(message)

    require(isinstance(catalog, dict), 'Catalog must be an object.')
    public = public or catalog.get('kind') in ('public', 'demo')
    require(catalog.get('schemaVersion') == 1 and type(catalog.get('schemaVersion')) is int, 'schemaVersion must equal 1.')
    require(catalog.get('kind') in (('demo', 'public') if public else ('private', 'demo', 'public')), 'Invalid catalog kind.')
    timestamp = catalog.get('generatedAt')
    require(isinstance(timestamp, str), 'generatedAt must be an ISO timestamp.')
    try:
        require(datetime.fromisoformat(timestamp.replace('Z', '+00:00')).tzinfo is not None, 'generatedAt requires a timezone.')
    except ValueError as exc:
        raise CatalogError('generatedAt must be an ISO timestamp.') from exc
    require(isinstance(catalog.get('movies'), list), 'movies must be an array.')
    if public:
        require(set(catalog) == {'schemaVersion', 'kind', 'generatedAt', 'movies'}, 'Public catalog has unexpected fields.')
    else:
        require(set(catalog) == {'schemaVersion', 'kind', 'generatedAt', 'movies'}, 'Private catalog has unexpected fields.')
    ids = set()
    for movie in catalog['movies']:
        require(isinstance(movie, dict), 'Movie must be an object.')
        required = {'id', 'title', 'year', 'genres', 'synopsis', 'links', 'sources'} | ({'poster', 'rights'} if public else {'posters', 'issues'})
        require(required.issubset(movie), 'Movie is missing required fields.')
        if public:
            require(set(movie) == required, 'Public movie has unexpected/private fields.')
        else:
            require(set(movie) == required, 'Private movie has unexpected fields.')
            require(isinstance(movie['posters'], list) and all(isinstance(path, str) for path in movie['posters']), 'Invalid private posters.')
            require(isinstance(movie['issues'], list) and all(isinstance(issue, str) for issue in movie['issues']), 'Invalid private issues.')
        require(isinstance(movie['id'], str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,100}', movie['id'])), 'Invalid movie id.')
        require(movie['id'] not in ids, 'Duplicate movie id.')
        ids.add(movie['id'])
        require(isinstance(movie['title'], str) and 0 < len(movie['title'].strip()) <= 500, 'Invalid title.')
        require(movie['year'] is None or type(movie['year']) is int and 1888 <= movie['year'] <= 2200, 'Invalid year.')
        require(isinstance(movie['genres'], list) and all(isinstance(g, str) and 0 < len(g) <= 100 for g in movie['genres']), 'Invalid genres.')
        require(len(set(movie['genres'])) == len(movie['genres']), 'Duplicate genres.')
        require(isinstance(movie['synopsis'], str) and len(movie['synopsis']) <= 10000, 'Invalid synopsis.')
        require(isinstance(movie['links'], list), 'Invalid links.')
        link_keys = set()
        for link in movie['links']:
            require(isinstance(link, dict) and set(link) == {'url', 'label', 'quality', 'size'}, 'Invalid link fields.')
            require(isinstance(link['url'], str) and bool(safe_url(link['url'])), 'Unsafe external URL.')
            require(isinstance(link['label'], str) and 0 < len(link['label']) <= 500, 'Invalid link label.')
            for key in ('quality', 'size'):
                require(link[key] is None or isinstance(link[key], str) and 0 < len(link[key]) <= 100, f'Invalid link {key}.')
            identity = (link['url'], link['quality'], link['size'])
            require(identity not in link_keys, 'Duplicate external link.')
            link_keys.add(identity)
        require(isinstance(movie['sources'], list), 'Invalid sources.')
        for source in movie['sources']:
            require(isinstance(source, dict), 'Invalid source object.')
            keys = {'channelId', 'channelName', 'messageId'}
            require(keys.issubset(source), 'Invalid source fields.')
            if public:
                require(set(source) == keys, 'Public sources contain private fields.')
            else:
                require(set(source) == keys | {'page'} and isinstance(source['page'], str), 'Invalid private source page.')
            require(all(isinstance(source[key], str) and 0 < len(source[key]) <= 500 for key in keys), 'Invalid source values.')
        if public:
            poster = movie['poster']
            require(poster is None or isinstance(poster, str) and bool(re.fullmatch(r'/posters/[A-Za-z0-9_-]+\.(?:webp|png|jpe?g|svg)', poster)), 'Invalid public poster path.')
            rights = movie['rights']
            require(isinstance(rights, dict) and set(rights) == {'distribution', 'poster', 'evidence'}, 'Invalid rights fields.')
            require(rights['distribution'] == 'cleared', 'Uncleared record cannot be published.')
            require(rights['poster'] in ('none', 'licensed', 'original'), 'Uncleared poster cannot be published.')
            require(isinstance(rights['evidence'], str) and 0 < len(rights['evidence'].strip()) <= 5000, 'Rights evidence is required.')
            require((poster is None) == (rights['poster'] == 'none'), 'Poster and poster rights disagree.')


def _page_sort(path: Path):
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)', path.as_posix())]



def import_archive(archive: Path, private_dir: Path, channel_id: str, channel_name: str, limits: Limits = Limits()) -> dict:
    """Serialize imports into one private store to prevent lost channel updates."""
    import fcntl
    private_dir = private_path(Path(private_dir))
    lock_path = private_dir / '.import.lock'
    if lock_path.is_symlink():
        raise CatalogError('Private import lock cannot be a symlink.')
    with lock_path.open('a') as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return _import_archive(archive, private_dir, channel_id, channel_name, limits)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

def _import_archive(archive: Path, private_dir: Path, channel_id: str, channel_name: str, limits: Limits = Limits()) -> dict:
    """Import one channel transactionally and refresh the active-channel catalog.

    The original ZIP is retained under archives/<sha256>.zip. A repeated identical
    import is idempotent. Importing a later archive replaces that channel's active
    view; earlier versions and inventories remain available for audit.
    """
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', channel_id):
        raise CatalogError('channel-id must be 1–100 ASCII letters, digits, _ or -.')
    if not isinstance(channel_name, str) or not channel_name.strip() or len(channel_name) > 500:
        raise CatalogError('channel-name is required and limited to 500 characters.')
    private_dir = private_path(Path(private_dir))
    archive = Path(archive).expanduser().resolve()
    if not archive.is_file():
        raise CatalogError('Archive file does not exist.')
    sha = digest_file(archive)
    registry_path = private_dir / 'registry.json'
    registry = read_json(registry_path) if registry_path.exists() else {'schemaVersion': 1, 'channels': {}}
    if not isinstance(registry, dict) or not isinstance(registry.get('channels'), dict):
        raise CatalogError('Invalid private channel registry.')
    active = dict(registry['channels'])
    folder = private_dir / 'imports' / channel_id / sha
    stage = Path(tempfile.mkdtemp(prefix='.import-', dir=private_dir))
    try:
        if folder.exists():
            inventory = read_json(folder / 'inventory.json')
            messages = read_json(folder / 'messages.json')
            # Names are caller-selected display metadata and can change on retry.
            for message in messages:
                message['channelName'] = channel_name
        else:
            inventory = safe_extract(archive, stage / 'extracted', limits)
            pages = sorted((p for p in (stage / 'extracted').rglob('*') if p.is_file() and re.fullmatch(r'messages\d*\.html', p.name, re.I)), key=_page_sort)
            if not pages:
                raise CatalogError('No messages*.html Telegram message pages were found.')
            messages = []
            identities = set()
            for page in pages:
                for message in parse_page(page, stage / 'extracted', channel_id, channel_name):
                    identity = (message['page'], message['id'])
                    if identity in identities:
                        raise CatalogError('Duplicate message identity within a message page.')
                    identities.add(identity)
                    message['posterPaths'] = [str(folder / 'extracted' / asset) for asset in message['posters']]
                    messages.append(message)
            _json_write(stage / 'inventory.json', inventory)
            _json_write(stage / 'messages.json', messages)
        active[channel_id] = {'name': channel_name, 'archiveSha256': sha, 'importPath': str(folder.relative_to(private_dir)), 'importedAt': now()}
        combined = []
        for identifier, entry in sorted(active.items()):
            if identifier == channel_id:
                combined.extend(messages)
            else:
                import_folder = (private_dir / entry['importPath']).resolve()
                if private_dir not in import_folder.parents:
                    raise CatalogError('Registry import path escapes private storage.')
                combined.extend(read_json(import_folder / 'messages.json'))
        movies, issues = merge_movies(combined)
        catalog = {'schemaVersion': 1, 'generatedAt': now(), 'kind': 'private', 'movies': movies}
        validate_catalog(catalog)
        codes: dict[str, int] = {}
        for issue in issues:
            code = issue['code']
            codes[code] = codes.get(code, 0) + 1
        report = {'schemaVersion': 1, 'generatedAt': now(), 'status': 'private_pending_review', 'channels': len(active), 'messages': len(combined), 'movies': len(movies), 'issuesByCode': codes, 'issues': issues, 'rules': ['No resolution inferred from file size.', 'Joined-message adjacency is not proof of shared poster ownership.', 'All imported records and URLs remain private until separately cleared.']}
        summary = {'channelId': channel_id, 'archiveSha256': sha, 'files': sum(item['kind'] == 'file' for item in inventory), 'entries': len(inventory), 'messagePages': sum(bool(re.fullmatch(r'messages\d*\.html', Path(item['path']).name, re.I)) for item in inventory), 'messages': len(messages), 'totalMovies': len(movies), 'issues': len(issues), 'status': 'private_pending_review'}
        _json_write(stage / 'report.json', summary)
        # Prepare every payload before changing the active registry. Older imports
        # remain recoverable even if interruption occurs during atomic replaces.
        if not folder.exists():
            folder.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.replace(stage, folder)
        archives = private_dir / 'archives'
        archives.mkdir(exist_ok=True, mode=0o700)
        retained = archives / f'{sha}.zip'
        if not retained.exists():
            temporary = archives / f'.{sha}.tmp'
            try:
                with archive.open('rb') as incoming, temporary.open('xb') as outgoing:
                    os.chmod(temporary, 0o600)
                    shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                if digest_file(temporary) != sha:
                    raise CatalogError('Archive changed while being retained; retry with a stable source.')
                os.replace(temporary, retained)
            finally:
                temporary.unlink(missing_ok=True)
        elif digest_file(retained) != sha:
            raise CatalogError('Retained archive integrity mismatch.')
        # The registry is the authoritative set of active imports. All files
        # below are atomically replaced; a failed run never truncates an output.
        _commit_private_state(private_dir, catalog, report, {'schemaVersion': 1, 'channels': active})
        return summary
    except (OSError, ValueError) as exc:
        if isinstance(exc, CatalogError):
            raise
        raise CatalogError(f'Import failed: {exc}') from exc
    finally:
        if stage.exists():
            shutil.rmtree(stage)



def _commit_private_state(private_dir: Path, catalog: dict, report: dict, registry: dict) -> None:
    """Install a complete generation; one atomic symlink swap commits all views."""
    state = private_dir / '.state'
    if state.is_symlink():
        raise CatalogError('Private state directory cannot be a symlink.')
    versions = state / 'versions'
    versions.mkdir(parents=True, exist_ok=True, mode=0o700)
    if versions.is_symlink():
        raise CatalogError('Private state versions directory cannot be a symlink.')
    current = state / 'current'
    if current.exists() and (not current.is_symlink() or not current.resolve().is_relative_to(versions.resolve())):
        raise CatalogError('Unexpected private state pointer.')
    names = ('movies.json', 'report.json', 'registry.json')
    for name in names:
        path = private_dir / name
        if path.is_symlink() and os.readlink(path) != f'.state/current/{name}':
            raise CatalogError('Refusing to overwrite an unexpected private output symlink.')
    generation = Path(tempfile.mkdtemp(prefix='generation-', dir=versions))
    temporary_pointer = state / '.current-next'
    try:
        for name, value in zip(names, (catalog, report, registry)):
            _json_write(generation / name, value)
        # Legacy ordinary JSON outputs are migrated without changing their
        # contents. The new canonical state is switched only after preparation.
        if not current.exists() and any((private_dir / name).is_file() for name in names):
            legacy = Path(tempfile.mkdtemp(prefix='legacy-', dir=versions))
            for name in names:
                old = private_dir / name
                if not old.is_file():
                    raise CatalogError('Incomplete legacy private state cannot be migrated.')
                shutil.copy2(old, legacy / name)
            os.symlink(legacy.relative_to(state), current)
        for name in names:
            path = private_dir / name
            if not path.is_symlink():
                alias = private_dir / ('.' + name + '-next')
                if alias.exists() or alias.is_symlink():
                    raise CatalogError('Unexpected private output staging file.')
                os.symlink(f'.state/current/{name}', alias)
                os.replace(alias, path)
        if temporary_pointer.exists() or temporary_pointer.is_symlink():
            raise CatalogError('Unexpected private state staging pointer.')
        os.symlink(generation.relative_to(state), temporary_pointer)
        os.replace(temporary_pointer, current)
    except Exception:
        temporary_pointer.unlink(missing_ok=True)
        if not current.is_symlink() or current.resolve() != generation.resolve():
            shutil.rmtree(generation)
        raise

def _sanitize_poster(source: Path, target: Path) -> None:
    try:
        import warnings
        from PIL import Image, ImageOps
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            previous_limit = Image.MAX_IMAGE_PIXELS
            Image.MAX_IMAGE_PIXELS = 20_000_000
            try:
                if source.stat().st_size > 30 * 1024**2:
                    raise CatalogError('Poster exceeds 30 MiB quota.')
                with Image.open(source) as original:
                    if original.format not in ('JPEG', 'PNG', 'WEBP'):
                        raise CatalogError('Only JPEG, PNG, and WebP licensed posters are supported.')
                    original.load()
                    cleaned = ImageOps.exif_transpose(original).convert('RGB')
                    cleaned.thumbnail((1800, 2700))
                    cleaned.save(target, 'WEBP', quality=88, method=6)
            finally:
                Image.MAX_IMAGE_PIXELS = previous_limit
    except ImportError as exc:
        raise CatalogError('Install requirements.txt to publish licensed raster posters.') from exc
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise CatalogError(f'Poster validation/re-encoding failed: {exc}') from exc


def publish_catalog(private_catalog: Path, manifest_path: Path, output: Path, assets_dir: Path | None = None) -> dict:
    """Publish only explicitly cleared records, individually allowlisted URLs.

    This command never publishes a raw archive, message text, source filename,
    archive-provided JS/CSS/HTML, unapproved links, or an unlicensed source image.
    """
    private_catalog, manifest_path, output = Path(private_catalog), Path(manifest_path), Path(output)
    catalog, manifest = read_json(private_catalog), read_json(manifest_path)
    validate_catalog(catalog)
    if catalog['kind'] != 'private':
        raise CatalogError('Publication requires a private imported catalog.')
    if not isinstance(manifest, dict) or set(manifest) != {'records'} or not isinstance(manifest['records'], list):
        raise CatalogError('Rights manifest must contain a records array only.')
    lookup = {movie['id']: movie for movie in catalog['movies']}
    public = {'schemaVersion': 1, 'generatedAt': now(), 'kind': 'public', 'movies': []}
    approved_ids = set()
    posters = []
    assets_dir = Path(assets_dir) if assets_dir else output.parent.parent / 'posters'
    if assets_dir.resolve() != (output.parent.parent / 'posters').resolve():
        raise CatalogError('Public assets directory must be the posters sibling of the data directory.')
    private_root = private_catalog.parent.resolve()
    ownership_path = private_root / 'publication-ownership.json'
    ownership = read_json(ownership_path) if ownership_path.exists() else {}
    if not isinstance(ownership, dict):
        raise CatalogError('Invalid private publication ownership registry.')
    output_key = str(output.resolve())
    previous_owned = ownership.get(output_key, {})
    if not isinstance(previous_owned, dict):
        raise CatalogError('Invalid private publication ownership entry.')
    if output.resolve() == private_catalog.resolve():
        raise CatalogError('Public output cannot overwrite the private catalog.')
    for approval in manifest['records']:
        if not isinstance(approval, dict) or set(approval) - {'id', 'distribution', 'evidence', 'links', 'poster'}:
            raise CatalogError('Unknown rights manifest fields.')
        identifier = approval.get('id')
        if identifier not in lookup or identifier in approved_ids:
            raise CatalogError('Rights manifest references an unknown or duplicate movie id.')
        approved_ids.add(identifier)
        evidence = approval.get('evidence')
        if approval.get('distribution') != 'cleared' or not isinstance(evidence, str) or not evidence.strip():
            raise CatalogError('Every published record requires explicit clearance and evidence.')
        movie = lookup[identifier]
        urls = approval.get('links')
        if not isinstance(urls, list) or not all(isinstance(url, str) for url in urls) or len(set(urls)) != len(urls):
            raise CatalogError('Rights manifest links must be a unique URL allowlist.')
        existing_urls = {link['url'] for link in movie['links']}
        if not set(urls).issubset(existing_urls):
            raise CatalogError('Rights manifest contains a URL not associated with its movie.')
        selected = [{key: movie[key] for key in ('id', 'title', 'year', 'genres', 'synopsis')}][0]
        selected['links'] = [dict(link) for link in movie['links'] if link['url'] in urls]
        selected['sources'] = [{key: source[key] for key in ('channelId', 'channelName', 'messageId')} for source in movie['sources']]
        poster = approval.get('poster', {'status': 'none'})
        if not isinstance(poster, dict) or set(poster) - {'status', 'path', 'evidence'}:
            raise CatalogError('Invalid poster clearance fields.')
        status = poster.get('status')
        selected['poster'] = None
        if status == 'licensed':
            poster_path = Path(poster.get('path', '')).expanduser().resolve()
            if not poster.get('evidence') or not isinstance(poster.get('evidence'), str):
                raise CatalogError('Licensed poster requires separate evidence.')
            permitted_posters = {Path(path).resolve() for path in movie.get('posters', [])}
            if poster_path not in permitted_posters or private_root not in poster_path.parents or not poster_path.is_file():
                raise CatalogError('Licensed poster must be an associated private import asset.')
            public_name = hashlib.sha256((identifier + digest_file(poster_path)).encode()).hexdigest()[:32] + '.webp'
            selected['poster'] = '/posters/' + public_name
            posters.append((poster_path, public_name))
        elif status != 'none' or set(poster) != {'status'}:
            raise CatalogError('Poster status must be none or licensed with evidence.')
        selected['rights'] = {'distribution': 'cleared', 'poster': status, 'evidence': evidence.strip()}
        public['movies'].append(selected)
    validate_catalog(public, public=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.publish-', dir=output.parent))
    try:
        for source, filename in posters:
            _sanitize_poster(source, staging / filename)
        # Validate before writing anything to the public tree. Track importer-
        # owned asset hashes in private storage, never in the public build.
        next_owned = {filename: digest_file(staging / filename) for _, filename in posters}
        stale = []
        for filename, expected_hash in previous_owned.items():
            if not re.fullmatch(r'[a-f0-9]{32}\.webp', filename) or not isinstance(expected_hash, str):
                raise CatalogError('Unsafe owned poster entry.')
            target = assets_dir / filename
            if target.is_symlink():
                raise CatalogError('Owned public poster was replaced with a symlink.')
            if target.exists() and digest_file(target) != expected_hash:
                raise CatalogError('Owned public poster was modified; refusing to overwrite or delete user changes.')
            if filename not in next_owned and target.exists():
                stale.append(target)
        if posters:
            assets_dir.mkdir(parents=True, exist_ok=True)
            for _, filename in posters:
                target = assets_dir / filename
                if target.is_symlink() or target.exists() and digest_file(target) != next_owned[filename]:
                    raise CatalogError('Public poster path already contains an unrelated or modified asset.')
                if not target.exists():
                    os.replace(staging / filename, target)
        _json_write(output, public)
        for target in stale:
            target.unlink()
        ownership[output_key] = next_owned
        _json_write(ownership_path, ownership)
    finally:
        shutil.rmtree(staging)
    return public
