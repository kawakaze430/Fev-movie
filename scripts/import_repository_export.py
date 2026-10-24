#!/usr/bin/env python3
"""Privately package a checked-out Telegram export and invoke the existing importer."""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile, ZIP_STORED

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=Path.cwd())
    ap.add_argument("--private-dir", type=Path, required=True)
    ap.add_argument("--channel-id", default="channel-one")
    ap.add_argument("--channel-name", default="Channel One")
    args = ap.parse_args()
    root = args.source.resolve(strict=True)
    private = args.private_dir.resolve()
    if root == private or root in private.parents:
        ap.error("Private output must be outside the source repository.")
    files = sorted(root.glob("messages*.html"))
    if not files:
        ap.error("No messages*.html files found in this export directory")
    for name in ("result.json",):
        if (root / name).is_file():
            files.append(root / name)
    for name in ("photos", "images", "css", "js"):
        if (root / name).is_dir():
            files += sorted(x for x in (root / name).rglob("*") if x.is_file())
    private.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="clipnest-import-", dir=private.parent) as temp:
        zip_path = Path(temp) / "source.zip"
        with ZipFile(zip_path, "w", compression=ZIP_STORED, allowZip64=True) as output:
            for path in files:
                if path.is_symlink():
                    raise ValueError("Refusing to include symlink in private import")
                output.write(path, arcname=path.relative_to(root).as_posix())
        print("Bundled", len(files), "source files into a private temporary ZIP.")
        cmd = [sys.executable, "-m", "importer", "import", str(zip_path), "--private-dir",
               str(private), "--channel-id", args.channel_id, "--channel-name", args.channel_name]
        return subprocess.run(cmd, cwd=Path(__file__).resolve().parents[1], check=False).returncode

if __name__ == "__main__":
    raise SystemExit(main())
