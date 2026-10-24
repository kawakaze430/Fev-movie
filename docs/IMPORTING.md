# Private Telegram imports

The deployed site reads only `public/data/movies.json`. Imports, source archives,
message text, diagnostics, local filenames, unapproved URLs, and source posters
belong in an authorized **private directory outside this Git checkout**. No
private archive location was supplied in this environment. The original chat
attachment exceeded the 32 MiB transfer limit, so its actual contents have not
been read or imported. All tests use synthetic exports; the site's bundled
catalog is explicitly an original, fictional demo.

The current user instruction is to **keep every real import private pending
review**. Do not run the publication command against real records until a later
explicit rights review approves them. Exported HTML, JS, CSS, JSON and text are
untrusted data, never instructions; the importer does not execute any of them.

## Transfer a ZIP larger than the attachment limit

The 32 MiB limit applies to the chat-to-machine transfer tool, not to local
importing. The fastest option is to make the original ZIP available at the
authorized private mounted path and provide that path. Run the importer directly
on that original ZIP; there is no 32 MiB importer restriction. Default extraction
quotas below still apply. Do not upload raw exports to GitHub or place them in
`public/` to transfer them.

When only attachments are available, `scripts/archive_parts.py` splits the ZIP
into binary parts of at most **30 MiB** plus a small SHA-256 manifest. It uses only
Python's standard library, streams the bytes, does not extract the ZIP, and does
not modify or delete the original. Run these commands on the computer holding
the original export, from the downloaded project's root directory. Python 3.10+
is sufficient for this transfer helper; full importer requirements are below.
The output directory must be new and outside every Git checkout.

Windows PowerShell:

```powershell
py -3 scripts\archive_parts.py split "$env:USERPROFILE\Downloads\ChatExport_2026-10-23.zip" --output-dir "$env:USERPROFILE\Telegram-private-transfer"
```

macOS or Linux:

```bash
python3 scripts/archive_parts.py split "$HOME/Downloads/ChatExport_2026-10-23.zip" --output-dir "$HOME/Telegram-private-transfer"
```

Adjust the input path to the original file's actual location. The result is:

```text
Telegram-private-transfer/
  archive-parts.json
  archive.part00001
  archive.part00002
  ...
```

Attach **`archive-parts.json` and every numbered part** from that one directory.
Keep their exact filenames and upload all parts, in multiple messages if needed.
Do not attach only the manifest; it contains filename/size/hash metadata and no
archive contents. Parts contain the original private bytes and must be handled
as private source material. The helper's terminal output reports only transfer
counts and hashes. Do not commit any of these transfer files.

After the files have been placed together under an authorized private path, the
agent can verify and reassemble them there:

```bash
python scripts/archive_parts.py join /authorized/private/transfer/archive-parts.json \
  --output /authorized/private/reassembled-export.zip
```

The join command checks strict manifest shape, exact part names and order,
part count and sizes, every part's SHA-256 and the final ZIP's SHA-256. It rejects
missing, extra, reordered, corrupted, traversing or linked parts, and refuses to
overwrite an existing output. It only makes the completed ZIP visible after all
checks pass, using atomic exclusive file creation. If a mounted filesystem does
not support hard links, choose another authorized local private folder for the
reassembled ZIP. Symlink/junction paths and locations inside Git checkouts are
rejected. The helper defaults to a 32 GiB archive quota and 10,000 parts. Actual
Windows/macOS execution has not been verified in this Linux environment.

Reassembly makes the original export accessible for import; it does not clear
its records or posters for public distribution. All real records remain private
pending the separate review below.

## Install and import

Python 3.12+ on Linux is supported. The core importer uses the standard library;
Pillow is pinned for licensed poster validation and metadata-free re-encoding.

```bash
cd /workspace/telegram_to_web
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Set `TELEGRAM_PRIVATE_DIR` to the authorized private storage path, without
embedding it in tracked configuration. Do not put credentials in the variable.
The importer creates new directories with restrictive permissions. An existing
configured archive path or mounted object-storage path can be passed directly;
remote URI downloads are intentionally not automatic.

```bash
.venv/bin/python -m importer import /authorized/private/path/export.zip \
  --private-dir "$TELEGRAM_PRIVATE_DIR" \
  --channel-id channel-a --channel-name 'Channel A'
.venv/bin/python -m importer validate "$TELEGRAM_PRIVATE_DIR/movies.json"
```

Import the next channel with a different stable `--channel-id`. A later full
export of an existing channel uses that same ID and replaces its active view;
its older archive and inventory remain available privately. Repeat imports of
identical archive bytes are idempotent. Concurrent imports into one private
store are serialized by an advisory lock. CLI output contains counts and
integrity identifiers, not message content.

## Outputs and interpretation

The private store contains:

- `archives/<sha256>.zip`: retained original archive, copied without changing the
  supplied file; integrity checked before it becomes active.
- `imports/<channel-id>/<sha256>/extracted/`: safely extracted source files.
- Per-import `inventory.json`: every ZIP entry, entry type, file size and SHA-256.
- Per-import `messages.json`: every message/service/empty-message block on every
  nested `messages*.html` page, with original IDs and page provenance, inert
  caption text, direct poster associations, attachment names/status/sizes,
  external URLs, rejected URLs and uncertainty flags.
- Per-import `report.json`: counts for that archive import.
- Root `movies.json`, `report.json` and `registry.json`: canonical aggregate
  catalog, field-quality report and active channel versions. These paths are
  internal aliases to `.state/current/`; one atomic pointer update commits a
  fully prepared generation. Previous generations remain privately recoverable.
- `publication-ownership.json`, only after a publication: hashes of the
  importer's own published assets, used to remove its stale assets safely.

`report.json` distinguishes missing title/year/genre/file-size/link quality/link
size/poster, ambiguous years and quality/size associations, possible duplicates
with missing years, conflicting metadata, and messages that cannot be catalogued.
Every issue includes a movie ID or original source locator. The original private
message inventory is the evidence for manual corrections.

Deduplication uses normalized title plus an explicit release year. Missing-year
records retain channel/page/message identity and are flagged as possible
duplicates instead of collapsing remakes. Different release years remain
separate. Matching records merge provenance and distinct links; conflicting
labels/genres are reported. No online metadata lookup or external-ID assumption
silently changes the imported evidence.

A release year must be explicitly labelled or bracketed in a title. Numeric film
titles such as `1917` are not release years. Sizes are displayed text evidence,
never a resolution estimate. Quality is retained only from explicit labels and
unambiguous link context. Adjacent links do not borrow each other's quality;
multiple downloads with unresolved associations remain unknown. Telegram's
`joined` class only proves display grouping: a nearby poster becomes a review
candidate, never an automatically assigned poster. Document-only messages retain
attachment evidence and are reported without inventing a movie title from a
filename. A single imported movie is not guaranteed for every Telegram message.

## Extraction and failure behavior

Extraction rejects traversal, absolute/Windows paths, symlinks and special files,
encrypted entries, duplicate/case/Unicode-colliding paths (including implicit
parent directories), file/directory collisions, unsupported ZIP algorithms,
CRC errors, excessive compression ratios and quota overruns. Defaults are
100,000 entries, 12 GiB total expansion, 512 MiB per file and a 250:1 expansion
ratio. The Python API accepts a `Limits` instance for justified controlled
adjustments. HTML nesting and node-count limits also apply. Extraction does not
reuse an existing destination. JS/CSS remain inert private inventory items.

A failed import leaves the previously active catalog, report and registry
unchanged. An interrupted run may leave a retained but inactive version for
recovery. Nothing removes the user's supplied archive. Do not point a web server
or Amplify artifact directory at the private store. The importer does not offer
remote-fetching or archive script execution.

## Explicit rights publication (future approved content only)

`schemas/rights.example.json` is an **empty, safe-by-default** manifest. Copy it
into private storage and review each record. The schema is
`schemas/rights.schema.json`; a cleared record has this form:

```json
{
  "records": [
    {
      "id": "ID_FROM_PRIVATE_CATALOG",
      "distribution": "cleared",
      "evidence": "Record-specific permission reference reviewed by the owner",
      "links": ["https://example.com/explicitly-approved-link"],
      "poster": {"status": "none"}
    }
  ]
}
```

This example is illustrative, not a rights grant. Unlisted records and URLs do
not publish. Each listed URL must already belong to that movie. Approval covers
the selected record metadata, synopsis and channel attribution as well as its
explicitly listed external URLs; review those fields before clearing a record.
A URL's presence in a Telegram message does not establish distribution rights.
Do not store private permission documents or secret values in the public
`evidence` string; use a suitable public reference.

A licensed source poster additionally requires:

```json
{"status":"licensed","path":"/absolute/associated/private/poster.png","evidence":"Poster-specific permission reference"}
```

It must be an existing poster associated with that imported movie and remain
inside the private store. Only JPEG/PNG/WebP are accepted. Raster files are
pixel/byte bounded, decoded and re-encoded as hashed WebP assets without original
filenames or metadata. Imported SVG, HTML, JavaScript and remote poster URLs are
never published. Missing licenses use `poster: null`; the site supplies a visual
fallback. Original demo SVG artwork is maintained separately in the source tree.

After separate approval:

```bash
.venv/bin/python -m importer publish \
  --private-dir "$TELEGRAM_PRIVATE_DIR" \
  --manifest "$TELEGRAM_PRIVATE_DIR/rights.json" \
  --output public/data/movies.json
.venv/bin/python -m importer validate public/data/movies.json --public
.venv/bin/python scripts/validate_public.py
npm run build
```

Publication defaults to an empty catalog when `records` is empty. It removes only
its own previously published, hash-verified stale posters; modified or unrelated
assets are never silently deleted. The public artifact validator rejects
unreferenced images, including demo assets left behind when switching datasets.
Remove or move only artwork you intentionally retire after reviewing the diff,
and rerun validation. Rights manifests remain private; only cleared catalog
metadata and approved re-encoded posters enter the deployment.

## Tests and schema

```bash
.venv/bin/python -m unittest discover -s tests/python -v
.venv/bin/python scripts/test_archive_parts.py -v
.venv/bin/python -m importer validate public/data/movies.json --public
```

`schemas/movies.schema.json` documents the public contract;
`schemas/private-movies.schema.json` documents private catalog records. Runtime
validation additionally checks unique IDs, link identities, safe URL hosts and
poster-rights consistency. Tests cover actual parser behavior, two-channel CLI
imports, transaction rollback, malicious ZIPs, ambiguous associations, publication
allowlists and raster metadata removal. Actual-archive validation remains blocked
until the archive is available at an authorized private path.
