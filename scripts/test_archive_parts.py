"""Roundtrip and tamper tests for private archive transfer parts.

All ZIP bytes are invented in a temporary directory outside the checkout.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from archive_parts import ArchivePartsError, join_archive, split_archive


class ArchivePartsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "synthetic-export.zip"
        with zipfile.ZipFile(self.source, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("messages.html", "<html><body>Synthetic transfer fixture only</body></html>")
            archive.writestr("data.json", '{"fixture":true}')
        self.original = self.source.read_bytes()
        self.repo = Path(__file__).resolve().parents[1]

    def tearDown(self):
        self.temporary.cleanup()

    def split(self):
        manifest = split_archive(self.source, self.root / "parts", part_size=13)
        return manifest, json.loads(manifest.read_text())

    def change_manifest(self, manifest, value):
        manifest.write_text(json.dumps(value))

    def test_split_manifest_inventory_and_exact_roundtrip(self):
        manifest, data = self.split()
        self.assertEqual(manifest.name, "archive-parts.json")
        self.assertEqual(set(data), {"version", "originalName", "size", "sha256", "partSize", "parts"})
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["originalName"], self.source.name)
        self.assertEqual(data["size"], len(self.original))
        self.assertEqual(data["sha256"], hashlib.sha256(self.original).hexdigest())
        self.assertEqual(data["partSize"], 13)
        self.assertGreater(len(data["parts"]), 1)
        for index, part in enumerate(data["parts"], 1):
            self.assertEqual(set(part), {"name", "size", "sha256"})
            self.assertEqual(part["name"], f"archive.part{index:05d}")
            content = (manifest.parent / part["name"]).read_bytes()
            self.assertEqual(part["size"], len(content))
            self.assertEqual(part["sha256"], hashlib.sha256(content).hexdigest())
            self.assertLessEqual(len(content), 13)
        self.source.unlink()
        result = join_archive(manifest, self.root / "joined.zip")
        self.assertEqual(result.read_bytes(), self.original)
        with zipfile.ZipFile(result) as archive:
            self.assertEqual(set(archive.namelist()), {"messages.html", "data.json"})

    def test_split_refuses_existing_destination_without_overwriting(self):
        output = self.root / "parts"
        output.mkdir()
        sentinel = output / "keep.txt"
        sentinel.write_text("keep")
        with self.assertRaises(ArchivePartsError):
            split_archive(self.source, output, part_size=13)
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertEqual(list(output.iterdir()), [sentinel])

    def test_split_rejects_invalid_part_sizes(self):
        for index, size in enumerate((0, -1, 30 * 1024**2 + 1)):
            with self.subTest(size=size), self.assertRaises(ArchivePartsError):
                split_archive(self.source, self.root / f"parts-{index}", part_size=size)

    def test_split_rejects_empty_source(self):
        source = self.root / "empty.zip"
        source.write_bytes(b"")
        with self.assertRaises(ArchivePartsError):
            split_archive(source, self.root / "parts", part_size=13)

    def test_split_rejects_source_inside_checkout(self):
        with self.assertRaises(ArchivePartsError):
            split_archive(Path(__file__), self.root / "parts", part_size=13)

    def test_split_rejects_any_git_ancestor_for_source(self):
        checkout = self.root / "other-checkout"
        nested = checkout / "private/nested"
        nested.mkdir(parents=True)
        (checkout / ".git").write_text("gitdir: /synthetic-only")
        source = nested / "export.zip"
        source.write_bytes(self.original)
        with self.assertRaises(ArchivePartsError):
            split_archive(source, self.root / "parts", part_size=13)

    def test_split_rejects_any_git_ancestor_for_destination(self):
        checkout = self.root / "other-checkout"
        checkout.mkdir()
        (checkout / ".git").mkdir()
        (checkout / ".git/HEAD").write_text("ref: refs/heads/main\n")
        output = checkout / "nested/parts"
        with self.assertRaises(ArchivePartsError):
            split_archive(self.source, output, part_size=13)
        self.assertFalse(output.exists())

    def test_split_rejects_destination_symlink_into_checkout(self):
        link = self.root / "repo-link"
        link.symlink_to(self.repo, target_is_directory=True)
        output = link / "should-never-contain-archive-parts"
        with self.assertRaises(ArchivePartsError):
            split_archive(self.source, output, part_size=13)
        self.assertFalse(output.exists())

    def test_join_refuses_existing_output_without_overwriting(self):
        manifest, _ = self.split()
        output = self.root / "joined.zip"
        output.write_bytes(b"keep")
        with self.assertRaises(ArchivePartsError):
            join_archive(manifest, output)
        self.assertEqual(output.read_bytes(), b"keep")

    def test_join_rejects_output_symlink(self):
        manifest, _ = self.split()
        sentinel = self.root / "sentinel"
        sentinel.write_bytes(b"keep")
        output = self.root / "joined.zip"
        output.symlink_to(sentinel)
        with self.assertRaises(ArchivePartsError):
            join_archive(manifest, output)
        self.assertEqual(sentinel.read_bytes(), b"keep")

    def test_join_rejects_output_parent_symlink_into_checkout(self):
        manifest, _ = self.split()
        link = self.root / "repo-link"
        link.symlink_to(self.repo, target_is_directory=True)
        output = link / "should-never-contain-joined-archive.zip"
        with self.assertRaises(ArchivePartsError):
            join_archive(manifest, output)
        self.assertFalse(output.exists())

    def test_join_rejects_missing_part(self):
        manifest, data = self.split()
        (manifest.parent / data["parts"][0]["name"]).unlink()
        output = self.root / "joined.zip"
        with self.assertRaises(ArchivePartsError):
            join_archive(manifest, output)
        self.assertFalse(output.exists())

    def test_join_rejects_corrupted_part_and_cleans_partial_output(self):
        manifest, data = self.split()
        part = manifest.parent / data["parts"][-1]["name"]
        content = part.read_bytes()
        part.write_bytes(bytes([content[0] ^ 1]) + content[1:])
        output = self.root / "joined.zip"
        with self.assertRaises(ArchivePartsError):
            join_archive(manifest, output)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob("*.partial")))

    def test_join_rejects_reordered_manifest(self):
        manifest, data = self.split()
        data["parts"] = list(reversed(data["parts"]))
        self.change_manifest(manifest, data)
        with self.assertRaises(ArchivePartsError):
            join_archive(manifest, self.root / "joined.zip")

    def test_join_rejects_traversing_part_name(self):
        manifest, data = self.split()
        data["parts"][0]["name"] = "../archive.part00001"
        self.change_manifest(manifest, data)
        with self.assertRaises(ArchivePartsError):
            join_archive(manifest, self.root / "joined.zip")

    def test_join_rejects_part_symlink_even_if_bytes_match(self):
        manifest, data = self.split()
        part = manifest.parent / data["parts"][0]["name"]
        other = self.root / "outside-part"
        other.write_bytes(part.read_bytes())
        part.unlink()
        part.symlink_to(other)
        with self.assertRaises(ArchivePartsError):
            join_archive(manifest, self.root / "joined.zip")

    def test_join_rejects_unlisted_extra_part(self):
        manifest, _ = self.split()
        (manifest.parent / "archive.part99999").write_bytes(b"unlisted")
        with self.assertRaises(ArchivePartsError):
            join_archive(manifest, self.root / "joined.zip")

    def test_join_checks_overall_hash_after_valid_part_hashes(self):
        manifest, data = self.split()
        data["sha256"] = "0" * 64
        self.change_manifest(manifest, data)
        output = self.root / "joined.zip"
        with self.assertRaises(ArchivePartsError):
            join_archive(manifest, output)
        self.assertFalse(output.exists())

    def test_join_rejects_tampered_part_size(self):
        manifest, data = self.split()
        data["parts"][0]["size"] += 1
        self.change_manifest(manifest, data)
        with self.assertRaises(ArchivePartsError):
            join_archive(manifest, self.root / "joined.zip")

    def test_join_rejects_total_size_over_limit(self):
        manifest, data = self.split()
        with self.assertRaises(ArchivePartsError):
            join_archive(manifest, self.root / "joined.zip", max_total_bytes=data["size"] - 1)

    def test_join_rejects_unknown_manifest_fields(self):
        manifest, data = self.split()
        data["execute"] = "do not execute this untrusted field"
        self.change_manifest(manifest, data)
        with self.assertRaises(ArchivePartsError):
            join_archive(manifest, self.root / "joined.zip")

    def test_join_rejects_boolean_size_metadata(self):
        manifest, data = self.split()
        data["size"] = True
        self.change_manifest(manifest, data)
        with self.assertRaises(ArchivePartsError):
            join_archive(manifest, self.root / "joined.zip")

    def test_join_rejects_bad_json(self):
        manifest, _ = self.split()
        manifest.write_text("{broken")
        with self.assertRaises(ArchivePartsError):
            join_archive(manifest, self.root / "joined.zip")

    def test_cli_roundtrip(self):
        script = self.repo / "scripts/archive_parts.py"
        parts = self.root / "cli-parts"
        result = subprocess.run([sys.executable, str(script), "split", str(self.source), "--output-dir", str(parts), "--part-size-mib", "1"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "split")
        self.assertEqual(summary["bytes"], len(self.original))
        self.assertNotIn(self.source.name, result.stdout)
        output = self.root / "cli-joined.zip"
        result = subprocess.run([sys.executable, str(script), "join", str(parts / "archive-parts.json"), "--output", str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_bytes(), self.original)

    def test_cli_missing_source_returns_failure_status(self):
        script = self.repo / "scripts/archive_parts.py"
        result = subprocess.run([sys.executable, str(script), "split", str(self.root / "missing.zip"), "--output-dir", str(self.root / "parts")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(str(self.root), result.stderr)
        self.assertFalse((self.root / "parts").exists())


if __name__ == "__main__":
    unittest.main()
