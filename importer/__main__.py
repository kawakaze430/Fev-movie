"""Command-line interface; prints counts only, never private message contents."""
import argparse
import json
import os
from pathlib import Path
import sys

from .catalog import CatalogError, import_archive, publish_catalog, read_json, validate_catalog


def main(argv=None):
    parser = argparse.ArgumentParser(description='Private Telegram HTML catalog importer')
    commands = parser.add_subparsers(dest='command', required=True)
    imported = commands.add_parser('import', help='Safely inventory and import one channel ZIP')
    imported.add_argument('archive', type=Path)
    imported.add_argument('--private-dir', type=Path, default=os.environ.get('TELEGRAM_PRIVATE_DIR'))
    imported.add_argument('--channel-id', required=True)
    imported.add_argument('--channel-name', required=True)
    validated = commands.add_parser('validate', help='Validate a private or public movies.json')
    validated.add_argument('catalog', type=Path)
    validated.add_argument('--public', action='store_true')
    published = commands.add_parser('publish', help='Build a public catalog from an explicit rights allowlist')
    published.add_argument('--private-dir', type=Path, default=os.environ.get('TELEGRAM_PRIVATE_DIR'))
    published.add_argument('--manifest', required=True, type=Path)
    published.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'import':
            if args.private_dir is None:
                raise CatalogError('--private-dir or TELEGRAM_PRIVATE_DIR is required; never store source exports in Git.')
            result = import_archive(args.archive, args.private_dir, args.channel_id, args.channel_name)
        elif args.command == 'validate':
            catalog = read_json(args.catalog)
            validate_catalog(catalog, public=args.public)
            result = {'valid': True, 'kind': catalog['kind'], 'movies': len(catalog['movies'])}
        else:
            if args.private_dir is None:
                raise CatalogError('--private-dir or TELEGRAM_PRIVATE_DIR is required.')
            catalog = publish_catalog(args.private_dir / 'movies.json', args.manifest, args.output)
            result = {'valid': True, 'kind': 'public', 'movies': len(catalog['movies'])}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except CatalogError as exc:
        print(f'Import error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
