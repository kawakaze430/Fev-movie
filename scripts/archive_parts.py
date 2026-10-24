#!/usr/bin/env python3
"""Split a private ZIP for attachment transfer, or verify and reassemble its parts.

Uses only Python's standard library on Windows, macOS, and Linux. Neither this
program nor its manifest executes source archive contents. All generated files
must remain outside Git checkouts; manifests and parts are private source data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

MIB = 1024 * 1024
DEFAULT_PART_SIZE = 30 * MIB
DEFAULT_MAX_TOTAL_BYTES = 32 * 1024**3
MAX_PARTS = 10_000
MAX_MANIFEST_BYTES = 8 * MIB
BUFFER_SIZE = MIB
MANIFEST_NAME = 'archive-parts.json'
SHA256 = re.compile(r'^[a-f0-9]{64}$')
PART_NAME = re.compile(r'^archive\.part\d{5}$')


class ArchivePartsError(ValueError):
    """Unsafe paths, invalid transfer metadata, or failed integrity checks."""


def _linked(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def _private_location(value: Path) -> Path:
    """Reject Git checkouts and symlink/junction path components, including leaf."""
    path = Path(os.path.abspath(Path(value).expanduser()))
    for component in (path, *path.parents):
        if _linked(component):
            raise ArchivePartsError('Source and output paths must not use symlinks or junctions.')
    resolved = path.resolve()
    for component in (resolved, *resolved.parents):
        marker = component / '.git'
        if marker.is_file() or marker.is_symlink() or marker.is_dir() and (marker / 'HEAD').is_file():
            raise ArchivePartsError('Archives, parts, and manifests must remain outside every Git checkout.')
    # Protect this project even if its Git metadata has not been copied along
    # with the source. Downloading only this standalone script does not classify
    # the user's entire home directory as a repository.
    project = Path(__file__).resolve().parents[1]
    if (project / 'package.json').is_file() and (project / 'importer').is_dir():
        if resolved == project or project in resolved.parents:
            raise ArchivePartsError('Private archive data cannot be placed inside this project.')
    return resolved


def _regular_file(path: Path):
    if _linked(path):
        raise ArchivePartsError('Refusing a linked input file.')
    try:
        info = path.stat()
    except OSError as exc:
        raise ArchivePartsError('A required input file is missing or unreadable.') from exc
    if not stat.S_ISREG(info.st_mode):
        raise ArchivePartsError('Every input must be a regular file.')
    return info


def _filename(value: object) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= 255 and value not in ('.', '..')
            and not any(character in value for character in '/\\:')
            and not any(ord(character) < 32 for character in value)
            and value.lower().endswith('.zip'))


def _integer(value: object, minimum: int = 1) -> bool:
    return type(value) is int and value >= minimum


def _sha(value: object) -> bool:
    return isinstance(value, str) and bool(SHA256.fullmatch(value))


def _write_manifest(path: Path, document: dict) -> None:
    raw = (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ArchivePartsError('Transfer manifest exceeds its bounded size limit.')
    with path.open('xb') as output:
        os.chmod(path, 0o600)
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def split_archive(source: Path, output_dir: Path, part_size: int = DEFAULT_PART_SIZE) -> Path:
    """Stream a private ZIP into uploadable binary parts; do not alter the ZIP."""
    if not _integer(part_size) or part_size > DEFAULT_PART_SIZE:
        raise ArchivePartsError('Part size must be between 1 byte and 30 MiB.')
    source, output_dir = _private_location(source), _private_location(output_dir)
    source_info = _regular_file(source)
    if not _filename(source.name):
        raise ArchivePartsError('Input must have a safe .zip filename.')
    if not 0 < source_info.st_size <= DEFAULT_MAX_TOTAL_BYTES:
        raise ArchivePartsError('Input ZIP must be nonempty and no larger than 32 GiB.')
    count = math.ceil(source_info.st_size / part_size)
    if count > MAX_PARTS:
        raise ArchivePartsError('Too many parts; select a larger part size.')
    if output_dir.exists() or _linked(output_dir):
        raise ArchivePartsError('Output directory already exists; refusing to overwrite it.')
    output_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _private_location(output_dir)
    created = False
    try:
        # Exclusive mkdir reserves the destination. The manifest is written last,
        # so a transfer never has a valid completion marker until all parts exist.
        output_dir.mkdir(mode=0o700)
        created = True
        parts, overall, remaining = [], hashlib.sha256(), source_info.st_size
        with source.open('rb') as incoming:
            opened = os.fstat(incoming.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (source_info.st_dev, source_info.st_ino, source_info.st_size, source_info.st_mtime_ns):
                raise ArchivePartsError('ZIP changed before splitting; retry with a stable source.')
            for index in range(1, count + 1):
                name = f'archive.part{index:05d}'
                length = min(part_size, remaining)
                part_hash, left = hashlib.sha256(), length
                with (output_dir / name).open('xb') as outgoing:
                    os.chmod(output_dir / name, 0o600)
                    while left:
                        block = incoming.read(min(BUFFER_SIZE, left))
                        if not block:
                            raise ArchivePartsError('ZIP was truncated while splitting.')
                        outgoing.write(block)
                        part_hash.update(block)
                        overall.update(block)
                        left -= len(block)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
                remaining -= length
                parts.append({'name': name, 'size': length, 'sha256': part_hash.hexdigest()})
            final = os.fstat(incoming.fileno())
            if incoming.read(1) or (final.st_size, final.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns):
                raise ArchivePartsError('ZIP changed while splitting; retry with a stable source.')
        document = {'version': 1, 'originalName': source.name, 'size': source_info.st_size,
                    'sha256': overall.hexdigest(), 'partSize': part_size, 'parts': parts}
        manifest = output_dir / MANIFEST_NAME
        _write_manifest(manifest, document)
        return manifest
    except Exception as exc:
        if created:
            shutil.rmtree(output_dir)
        if isinstance(exc, ArchivePartsError):
            raise
        if isinstance(exc, OSError):
            raise ArchivePartsError('Cannot safely write archive parts; no completed transfer was created.') from exc
        raise


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArchivePartsError('Manifest contains duplicate JSON keys.')
        result[key] = value
    return result


def _read_manifest(path: Path, max_total_bytes: int) -> dict:
    info = _regular_file(path)
    if info.st_size > MAX_MANIFEST_BYTES:
        raise ArchivePartsError('Transfer manifest is too large.')
    try:
        with path.open('rb') as incoming:
            raw = incoming.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ArchivePartsError('Transfer manifest is too large.')
        document = json.loads(raw.decode('utf-8'), object_pairs_hook=_no_duplicate_keys)
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, ArchivePartsError):
            raise
        raise ArchivePartsError('Transfer manifest must be readable, valid UTF-8 JSON.') from exc
    expected = {'version', 'originalName', 'size', 'sha256', 'partSize', 'parts'}
    if not isinstance(document, dict) or set(document) != expected:
        raise ArchivePartsError('Transfer manifest has missing or unknown fields.')
    if type(document['version']) is not int or document['version'] != 1 or not _filename(document['originalName']):
        raise ArchivePartsError('Unsupported manifest version or unsafe original filename.')
    if not _integer(document['size']) or document['size'] > max_total_bytes or not _sha(document['sha256']):
        raise ArchivePartsError('Manifest archive size or SHA-256 is invalid or exceeds quota.')
    if not _integer(document['partSize']) or document['partSize'] > DEFAULT_PART_SIZE:
        raise ArchivePartsError('Manifest part size must be between 1 byte and 30 MiB.')
    parts = document['parts']
    count = math.ceil(document['size'] / document['partSize'])
    if not isinstance(parts, list) or not 0 < len(parts) <= MAX_PARTS or len(parts) != count:
        raise ArchivePartsError('Manifest part count does not match the declared archive size.')
    remaining = document['size']
    for index, part in enumerate(parts, 1):
        if not isinstance(part, dict) or set(part) != {'name', 'size', 'sha256'}:
            raise ArchivePartsError('Invalid part manifest fields.')
        if part['name'] != f'archive.part{index:05d}':
            raise ArchivePartsError('Parts must have exact sequential names in the declared order.')
        expected_size = min(document['partSize'], remaining)
        if not _integer(part['size']) or part['size'] != expected_size or not _sha(part['sha256']):
            raise ArchivePartsError('Part size or SHA-256 does not match the transfer contract.')
        remaining -= part['size']
    return document


def join_archive(manifest: Path, output: Path, max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES) -> Path:
    """Validate every part and stream to a verified, atomic, exclusive ZIP output."""
    if not _integer(max_total_bytes) or max_total_bytes > DEFAULT_MAX_TOTAL_BYTES:
        raise ArchivePartsError('Join quota must be between 1 byte and 32 GiB.')
    manifest, output = _private_location(manifest), _private_location(output)
    document = _read_manifest(manifest, max_total_bytes)
    if not _filename(output.name):
        raise ArchivePartsError('Output must have a safe .zip filename.')
    if output.exists() or _linked(output):
        raise ArchivePartsError('Output already exists; refusing to overwrite it.')
    expected_names = {part['name'] for part in document['parts']}
    found_names = {entry.name for entry in manifest.parent.glob('archive.part*')}
    if found_names != expected_names:
        raise ArchivePartsError('Transfer directory has missing or unexpected archive parts.')
    # Preflight existence and size before creating output files. Paths are exact
    # fixed names, never paths supplied by archive or manifest text.
    for part in document['parts']:
        path = _private_location(manifest.parent / part['name'])
        if _regular_file(path).st_size != part['size']:
            raise ArchivePartsError('Part length does not match its manifest.')
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _private_location(output)
    fd, temporary_name = tempfile.mkstemp(prefix='.archive-join-', suffix='.partial', dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, 'wb') as outgoing:
            overall, total = hashlib.sha256(), 0
            for part in document['parts']:
                source = _private_location(manifest.parent / part['name'])
                _regular_file(source)
                part_hash, read_size = hashlib.sha256(), 0
                with source.open('rb') as incoming:
                    while True:
                        # One-byte lookahead ensures an enlarged input cannot
                        # silently exceed its declared size or memory bound.
                        block = incoming.read(min(BUFFER_SIZE, part['size'] - read_size + 1))
                        if not block:
                            break
                        read_size += len(block)
                        total += len(block)
                        if read_size > part['size'] or total > document['size'] or total > max_total_bytes:
                            raise ArchivePartsError('Part changed or exceeded the join size quota.')
                        part_hash.update(block)
                        overall.update(block)
                        outgoing.write(block)
                if read_size != part['size'] or part_hash.hexdigest() != part['sha256']:
                    raise ArchivePartsError('Part integrity check failed; output was not created.')
            if total != document['size'] or overall.hexdigest() != document['sha256']:
                raise ArchivePartsError('Final archive SHA-256 does not match the original ZIP.')
            outgoing.flush()
            os.fsync(outgoing.fileno())
        # A hard link is an atomic, no-overwrite publication of the complete
        # verified bytes on Windows/NTFS and ordinary macOS/Linux filesystems.
        # If the selected filesystem cannot do this, fail without falling back
        # to a rename that could overwrite another user's file.
        _private_location(output)
        try:
            os.link(temporary, output)
        except FileExistsError as exc:
            raise ArchivePartsError('Output appeared during reassembly; refusing to overwrite it.') from exc
        except OSError as exc:
            raise ArchivePartsError('Output filesystem must support atomic hard-link creation; choose a local private folder.') from exc
        return output
    except OSError as exc:
        raise ArchivePartsError('Cannot safely read parts or write the reassembled archive.') from exc
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    split = commands.add_parser('split', help='Create private binary parts and a hash manifest')
    split.add_argument('source', type=Path)
    split.add_argument('--output-dir', required=True, type=Path)
    split.add_argument('--part-size-mib', type=int, default=30, choices=range(1, 31), metavar='1..30')
    joined = commands.add_parser('join', help='Verify and combine all parts without overwriting output')
    joined.add_argument('manifest', type=Path)
    joined.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'split':
            manifest = split_archive(args.source, args.output_dir, args.part_size_mib * MIB)
            document = _read_manifest(manifest, DEFAULT_MAX_TOTAL_BYTES)
            summary = {'status': 'split', 'parts': len(document['parts']), 'bytes': document['size'], 'sha256': document['sha256']}
        else:
            output = join_archive(args.manifest, args.output)
            document = _read_manifest(args.manifest, DEFAULT_MAX_TOTAL_BYTES)
            summary = {'status': 'joined', 'parts': len(document['parts']), 'bytes': output.stat().st_size, 'sha256': document['sha256']}
        print(json.dumps(summary))
        return 0
    except (ArchivePartsError, OSError) as exc:
        # Messages intentionally omit source filenames, contents and private
        # paths; they are actionable without printing private source metadata.
        print(f'Archive transfer error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
