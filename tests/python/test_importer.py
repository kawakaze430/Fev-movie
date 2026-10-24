"""Synthetic regression tests; never load or embed a real channel export."""
from __future__ import annotations

import json
import io
import os
import subprocess
import sys
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

from importer.catalog import (
    CatalogError, Limits, import_archive, merge_movies, parse_metadata,
    parse_page, publish_catalog, safe_extract, validate_catalog,
)


class ImporterCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def zip(self, files, name="export.zip"):
        path = self.root / name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, body in files.items():
                archive.writestr(name, body)
        return path

    def page(self, messages, name="messages.html"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"<!doctype html><html><body>{messages}</body></html>", encoding="utf-8")
        return path

    def message(self, identifier, text, extra="", classes="message default clearfix"):
        return f'<div class="{classes}" id="message{identifier}"><div class="body">{extra}<div class="text">{text}</div></div></div>'


class ExtractionTests(ImporterCase):
    def test_inventories_every_file_with_integrity_hash(self):
        archive = self.zip({"nested/messages.html": "hello", "photos/p.jpg": b"poster", "css/style.css": "body{}", "scripts/x.js": "throw 'do not run'", "data.json": "{}"})
        inventory = safe_extract(archive, self.root / "out")
        self.assertEqual({item["path"] for item in inventory}, {"nested/messages.html", "photos/p.jpg", "css/style.css", "scripts/x.js", "data.json"})
        self.assertTrue(all(len(item["sha256"]) == 64 for item in inventory))
        self.assertEqual((self.root / "out/nested/messages.html").read_text(), "hello")

    def test_rejects_parent_path_traversal(self):
        with self.assertRaises(CatalogError):
            safe_extract(self.zip({"../escaped.txt": "bad"}), self.root / "out")
        self.assertFalse((self.root / "escaped.txt").exists())

    def test_rejects_absolute_paths_and_windows_paths(self):
        for name in ("/absolute.txt", "C:/escape.txt", "..\\escape.txt"):
            with self.subTest(name=name), self.assertRaises(CatalogError):
                safe_extract(self.zip({name: "bad"}, f"bad-{len(name)}.zip"), self.root / f"out-{len(name)}")

    def test_rejects_symbolic_links(self):
        path = self.root / "link.zip"
        info = zipfile.ZipInfo("photos/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(info, "../../outside")
        with self.assertRaises(CatalogError):
            safe_extract(path, self.root / "out")

    def test_rejects_case_collisions(self):
        with self.assertRaises(CatalogError):
            safe_extract(self.zip({"photos/Poster.jpg": "one", "photos/poster.jpg": "two"}), self.root / "out")

    def test_rejects_implicit_case_colliding_parent_directories(self):
        with self.assertRaises(CatalogError):
            safe_extract(self.zip({"A/x.jpg": "one", "a/y.jpg": "two"}), self.root / "out")

    def test_rejects_file_count_quota(self):
        with self.assertRaises(CatalogError):
            safe_extract(self.zip({"a": "one", "b": "two"}), self.root / "out", Limits(max_files=1))

    def test_rejects_total_size_quota(self):
        with self.assertRaises(CatalogError):
            safe_extract(self.zip({"a": "123456", "b": "123456"}), self.root / "out", Limits(max_total_bytes=10))

    def test_rejects_compression_bombs(self):
        with self.assertRaises(CatalogError):
            safe_extract(self.zip({"bomb": "a" * 100000}), self.root / "out", Limits(max_ratio=5))

    def test_rejects_existing_destination_data(self):
        dest = self.root / "out"
        dest.mkdir()
        (dest / "keep.txt").write_text("existing")
        with self.assertRaises(CatalogError):
            safe_extract(self.zip({"keep.txt": "replacement"}), dest)
        self.assertEqual((dest / "keep.txt").read_text(), "existing")


class MetadataTests(unittest.TestCase):
    def test_extracts_explicit_fields(self):
        result = parse_metadata("Title: Synthetic Orbit\nYear: 2021\nGenre: Science Fiction, Adventure\nQuality: 1080p\nSize: 1.4 GB")
        self.assertEqual(result["title"], "Synthetic Orbit")
        self.assertEqual(result["year"], 2021)
        self.assertIn("Science Fiction", result["genres"])
        self.assertIn("1080p", result["qualities"])
        self.assertTrue(result["sizes"])

    def test_never_guesses_resolution_from_file_size(self):
        result = parse_metadata("Title: Small Film\nSize: 700 MB")
        self.assertEqual(result["qualities"], [])
        self.assertIsNone(result["year"])

    def test_numeric_movie_names_are_not_release_years(self):
        for title in ("1917", "2001: A Space Odyssey"):
            with self.subTest(title=title):
                result = parse_metadata("Title: " + title)
                self.assertEqual(result["title"], title)
                self.assertIsNone(result["year"])
                self.assertIn("missing_year", result["issues"])

    def test_out_of_range_year_is_reported_without_invention(self):
        metadata = parse_metadata("Title: Old Story\nYear: 1800")
        self.assertIsNone(metadata["year"])
        self.assertIn("invalid_year", metadata["issues"])

    def test_bracketed_year_is_explicit_evidence(self):
        result = parse_metadata("Title: Orbit (2021)")
        self.assertEqual(result["title"], "Orbit")
        self.assertEqual(result["year"], 2021)

    def test_ambiguous_year_is_reported(self):
        result = parse_metadata("Title: Two Dates\nYear: 1995 / 2022")
        self.assertIsNone(result["year"])
        self.assertTrue(result["issues"])


class HtmlTests(ImporterCase):
    def test_preserves_direct_poster_association_and_safe_urls(self):
        (self.root / "photos").mkdir()
        (self.root / "photos/poster.jpg").write_bytes(b"fake fixture image")
        path = self.page(self.message("7", 'Title: Orbit (2021)<br>Genre: Adventure<br><a href="https://example.com/watch?x=1&amp;y=2">1080p 1 GB</a><a href="javascript:alert(1)">bad</a>', '<a class="photo_wrap" href="photos/poster.jpg"><img class="photo" src="photos/poster.jpg"></a>'))
        messages = parse_page(path, self.root, "channel-a", "Channel A")
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]["id"]), "message7")
        self.assertTrue(any("poster.jpg" in p for p in messages[0]["posters"]))
        self.assertEqual([u["url"] for u in messages[0]["urls"]], ["https://example.com/watch?x=1&y=2"])

    def test_adjacent_anchors_do_not_share_quality_evidence(self):
        path = self.page(self.message("9", 'Title: Unlabelled Mirror<br><a href="https://example.com/first">1080p</a> <a href="https://example.com/second">Download</a>'))
        message = parse_page(path, self.root, "a", "A")[0]
        self.assertEqual([link["quality"] for link in message["urls"]], ["1080p", None])
        self.assertIn("missing_link_quality", message["issues"])

    def test_malformed_photo_href_is_reported_without_crashing(self):
        path = self.page(self.message("11", "Title: Bad Photo", '<a class="photo_wrap" href="http://[invalid"><img class="photo" src="missing.jpg"></a>'))
        message = parse_page(path, self.root, "a", "A")[0]
        self.assertEqual(message["posters"], [])
        self.assertIn("missing_poster_asset", message["issues"])

    def test_document_attachments_are_inventoried_with_explicit_evidence(self):
        (self.root / "files").mkdir()
        (self.root / "files/Orbit.1080p.mkv").write_bytes(b"synthetic media fixture")
        document = '<a class="media_wrap clearfix" href="files/Orbit.1080p.mkv"><div class="media clearfix pull_left media_file"><div class="body"><div class="title bold">Orbit.1080p.mkv</div><div class="status details">1.4 GB</div></div></div></a>'
        path = self.page(self.message("12", "Title: Orbit<br>Year: 2020", document))
        message = parse_page(path, self.root, "a", "A")[0]
        self.assertEqual(len(message["attachments"]), 1)
        attachment = message["attachments"][0]
        self.assertEqual(attachment["name"], "Orbit.1080p.mkv")
        self.assertEqual(attachment["path"], "files/Orbit.1080p.mkv")
        self.assertTrue(attachment["exists"])
        self.assertIn("1080p", attachment["qualities"])
        self.assertIn("1.4 GB", attachment["sizes"])
        self.assertIn("1080p", message["metadata"]["qualities"])
        self.assertIn("1.4 GB", message["metadata"]["sizes"])

    def test_document_filename_without_caption_does_not_invent_movie(self):
        document = '<a class="media_wrap clearfix" href="files/No-Caption.720p.mkv"><div class="media clearfix pull_left media_file"><div class="body"><div class="title bold">No-Caption.720p.mkv</div><div class="status details">700 MB</div></div></div></a>'
        archive = self.zip({"messages.html": self.message("13", "", document)})
        private = self.root / "private"
        import_archive(archive, private, "a", "A")
        catalog = json.loads((private / "movies.json").read_text())
        self.assertEqual(catalog["movies"], [])
        report = json.loads((private / "report.json").read_text())
        self.assertIn("attachment_without_caption", report["issuesByCode"])
        inventory = next(private.glob("imports/a/*/messages.json"))
        messages = json.loads(inventory.read_text())
        self.assertEqual(len(messages[0]["attachments"]), 1)
        self.assertFalse(messages[0]["attachments"][0]["exists"])

    def test_identical_link_labels_keep_their_own_line_quality(self):
        path = self.page(self.message("9", 'Title: Two Encodes<br>Year: 2020<br>1080p 1 GB <a href="https://example.com/hd">Download</a><br>720p 700 MB <a href="https://example.com/sd">Download</a>'))
        message = parse_page(path, self.root, "a", "A")[0]
        quality_by_url = {link["url"]: link["quality"] for link in message["urls"]}
        self.assertEqual(quality_by_url, {"https://example.com/hd": "1080p", "https://example.com/sd": "720p"})

    def test_does_not_use_avatars_as_movie_posters(self):
        (self.root / "photos").mkdir()
        (self.root / "photos/avatar.jpg").write_bytes(b"synthetic avatar")
        path = self.page(self.message("8", "Title: No Poster", '<div class="userpic"><img src="photos/avatar.jpg"></div>'))
        messages = parse_page(path, self.root, "a", "A")
        self.assertEqual(messages[0]["posters"], [])

    def test_joined_caption_flags_ambiguous_adjacent_poster(self):
        (self.root / "photos").mkdir()
        (self.root / "photos/poster.jpg").write_bytes(b"synthetic poster")
        photo = self.message("1", "", '<a class="photo_wrap" href="photos/poster.jpg"><img class="photo" src="photos/poster.jpg"></a>')
        caption = self.message("2", "Title: Uncertain Album", classes="message default clearfix joined")
        path = self.page(photo + caption)
        messages = parse_page(path, self.root, "a", "A")
        self.assertEqual(messages[1]["posters"], [])
        self.assertIn("ambiguous_adjacent_poster", messages[1]["issues"])

    def test_inventories_service_and_empty_messages(self):
        path = self.page('<div class="message service" id="message-1"><div class="body details">Channel created</div></div>' + self.message("2", ""))
        messages = parse_page(path, self.root, "a", "A")
        self.assertEqual(len(messages), 2)

    def test_ignores_scripts_and_styles_as_text(self):
        path = self.page(self.message("1", 'Title: Safe Film<script>Title: Injected</script><style>body {display:none}</style>'))
        message = parse_page(path, self.root, "a", "A")[0]
        self.assertNotIn("Injected", message["text"])
        self.assertNotIn("display:none", message["text"])


class IntegrationTests(ImporterCase):
    def test_imports_all_message_pages_and_is_repeatable(self):
        html1 = self.message("1", 'Title: First Film<br>Year: 2020<br>Genre: Drama<br><a href="https://example.com/a">720p 700 MB</a>')
        html2 = self.message("2", 'Title: Second Film<br>Year: 2021<br>Genre: Comedy')
        archive = self.zip({"channel/messages.html": html1, "channel/messages2.html": html2, "channel/data.json": "{}"})
        private = self.root / "private"
        import_archive(archive, private, "channel-a", "Channel A")
        first = json.loads((private / "movies.json").read_text())
        self.assertEqual(len(first["movies"]), 2)
        import_archive(archive, private, "channel-a", "Channel A")
        second = json.loads((private / "movies.json").read_text())
        self.assertEqual([m["id"] for m in first["movies"]], [m["id"] for m in second["movies"]])
        self.assertEqual(len(second["movies"]), 2)
        self.assertTrue(list(private.rglob("inventory.json")))
        self.assertTrue(list(private.rglob("messages.json")))
        self.assertTrue((private / "report.json").exists())

    def test_multi_channel_dedup_keeps_both_sources(self):
        one = self.zip({"messages.html": self.message("1", "Title: Shared Film<br>Year: 2020<br>Genre: Drama")}, "one.zip")
        two = self.zip({"messages.html": self.message("2", "Title: Shared Film<br>Year: 2020<br>Genre: Drama")}, "two.zip")
        private = self.root / "private"
        import_archive(one, private, "a", "A")
        import_archive(two, private, "b", "B")
        movies = json.loads((private / "movies.json").read_text())["movies"]
        self.assertEqual(len(movies), 1)
        self.assertEqual({s["channelId"] for s in movies[0]["sources"]}, {"a", "b"})

    def test_failed_archive_does_not_replace_active_outputs(self):
        archive = self.zip({"messages.html": self.message("1", "Title: Keep Film<br>Year: 2020")})
        private = self.root / "private"
        import_archive(archive, private, "a", "A")
        before = {name: (private / name).read_bytes() for name in ("movies.json", "report.json", "registry.json")}
        bad_archive = self.zip({"../escaped": "bad"}, "bad.zip")
        with self.assertRaises(CatalogError):
            import_archive(bad_archive, private, "a", "A")
        self.assertEqual(before, {name: (private / name).read_bytes() for name in before})
        self.assertFalse(any(private.glob(".import-*")))

    def test_same_link_identity_with_conflicting_labels_deduplicates(self):
        first = self.zip({"messages.html": self.message("1", 'Title: Shared Link<br>Year: 2020<br><a href="https://example.com/shared">Mirror A 1080p 1 GB</a>')}, "first-link.zip")
        second = self.zip({"messages.html": self.message("2", 'Title: Shared Link<br>Year: 2020<br><a href="https://example.com/shared">Mirror B 1080p 1 GB</a>')}, "second-link.zip")
        private = self.root / "private"
        import_archive(first, private, "a", "A")
        import_archive(second, private, "b", "B")
        catalog = json.loads((private / "movies.json").read_text())
        validate_catalog(catalog)
        self.assertEqual(len(catalog["movies"]), 1)
        self.assertEqual(len(catalog["movies"][0]["links"]), 1)
        report = json.loads((private / "report.json").read_text())
        self.assertIn("conflicting_link_labels", report["issuesByCode"])

    def test_invalid_year_import_remains_available_for_review(self):
        archive = self.zip({"messages.html": self.message("1", "Title: Old Story<br>Year: 1800")})
        private = self.root / "private"
        import_archive(archive, private, "a", "A")
        catalog = json.loads((private / "movies.json").read_text())
        self.assertIsNone(catalog["movies"][0]["year"])
        self.assertIn("invalid_year", catalog["movies"][0]["issues"])

    def test_failed_aggregate_write_preserves_all_active_outputs(self):
        from importer import catalog as implementation
        first = self.zip({"messages.html": self.message("1", "Title: Original<br>Year: 2020")}, "original.zip")
        second = self.zip({"messages.html": self.message("2", "Title: Replacement<br>Year: 2021")}, "replacement.zip")
        private = self.root / "private"
        import_archive(first, private, "a", "A")
        names = ("movies.json", "report.json", "registry.json")
        before = {name: (private / name).read_bytes() for name in names}
        original_write = implementation._json_write
        injected = False
        def fail_report_once(path, data):
            nonlocal injected
            if not injected and isinstance(data, dict) and "issuesByCode" in data:
                injected = True
                raise OSError("synthetic disk write failure")
            return original_write(path, data)
        with mock.patch.object(implementation, "_json_write", side_effect=fail_report_once):
            with self.assertRaises(CatalogError):
                import_archive(second, private, "a", "A")
        self.assertTrue(injected)
        self.assertEqual(before, {name: (private / name).read_bytes() for name in names})
        validate_catalog(json.loads((private / "movies.json").read_text()))

    def test_different_years_remain_separate(self):
        archive = self.zip({"messages.html": self.message("1", "Title: Shared Film<br>Year: 1980") + self.message("2", "Title: Shared Film<br>Year: 2020")})
        private = self.root / "private"
        import_archive(archive, private, "a", "A")
        self.assertEqual(len(json.loads((private / "movies.json").read_text())["movies"]), 2)


class PublicationTests(ImporterCase):
    def imported_catalog(self):
        archive = self.zip({"messages.html": self.message("42", 'Title: Review Film<br>Year: 2022<br>Genre: Drama<br><a href="https://example.com/approved">1080p 1 GB</a><br><a href="https://example.com/private">720p 700 MB</a>')})
        private = self.root / "private"
        import_archive(archive, private, "review-channel", "Review Channel")
        catalog = private / "movies.json"
        movie = json.loads(catalog.read_text())["movies"][0]
        return catalog, movie

    def manifest(self, records):
        path = self.root / "rights.json"
        path.write_text(json.dumps({"records": records}))
        return path

    def test_publication_defaults_to_empty_without_clearance(self):
        catalog, movie = self.imported_catalog()
        out = self.root / "public/movies.json"
        publish_catalog(catalog, self.manifest([]), out)
        result = json.loads(out.read_text())
        self.assertEqual(result["movies"], [])
        self.assertNotIn("Review Film", out.read_text())

    def test_publication_only_exports_explicitly_cleared_links(self):
        catalog, movie = self.imported_catalog()
        out = self.root / "public/movies.json"
        rights = {"id": movie["id"], "distribution": "cleared", "evidence": "Synthetic test rights statement", "links": ["https://example.com/approved"], "poster": {"status": "none"}}
        publish_catalog(catalog, self.manifest([rights]), out)
        result = json.loads(out.read_text())
        validate_catalog(result)
        self.assertEqual(len(result["movies"]), 1)
        self.assertEqual([link["url"] for link in result["movies"][0]["links"]], ["https://example.com/approved"])
        self.assertNotIn("https://example.com/private", out.read_text())
        self.assertNotIn("rawText", out.read_text())
        self.assertIsNone(result["movies"][0]["poster"])

    def test_licensed_poster_is_reencoded_without_private_metadata(self):
        from PIL import Image, PngImagePlugin
        buffer = io.BytesIO()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Comment", "private synthetic metadata")
        Image.new("RGB", (20, 30), "navy").save(buffer, format="PNG", pnginfo=metadata)
        archive = self.zip({"messages.html": self.message("3", "Title: Licensed Test<br>Year: 2020", '<a class="photo_wrap" href="photos/p.png"><img class="photo" src="photos/p.png"></a>'), "photos/p.png": buffer.getvalue()})
        private = self.root / "private"
        import_archive(archive, private, "a", "A")
        catalog = private / "movies.json"
        movie = json.loads(catalog.read_text())["movies"][0]
        rights = {"id": movie["id"], "distribution": "cleared", "evidence": "Synthetic fixture ownership", "links": [], "poster": {"status": "licensed", "path": movie["posters"][0], "evidence": "Synthetic fixture ownership"}}
        out = self.root / "public/data/movies.json"
        result = publish_catalog(catalog, self.manifest([rights]), out)
        poster = self.root / "public" / result["movies"][0]["poster"].lstrip("/")
        self.assertEqual(poster.suffix, ".webp")
        self.assertNotIn(b"private synthetic metadata", poster.read_bytes())
        with Image.open(poster) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (20, 30))
            self.assertNotIn("Comment", image.info)

    def test_republishing_empty_catalog_removes_only_owned_stale_posters(self):
        from PIL import Image
        buffer = io.BytesIO()
        Image.new("RGB", (10, 15), "teal").save(buffer, format="PNG")
        archive = self.zip({"messages.html": self.message("3", "Title: Removal Test<br>Year: 2020", '<a class="photo_wrap" href="photos/p.png"><img class="photo" src="photos/p.png"></a>'), "photos/p.png": buffer.getvalue()})
        private = self.root / "private"
        import_archive(archive, private, "a", "A")
        catalog = private / "movies.json"
        movie = json.loads(catalog.read_text())["movies"][0]
        rights = {"id": movie["id"], "distribution": "cleared", "evidence": "Synthetic fixture ownership", "links": [], "poster": {"status": "licensed", "path": movie["posters"][0], "evidence": "Synthetic fixture ownership"}}
        out = self.root / "public/data/movies.json"
        result = publish_catalog(catalog, self.manifest([rights]), out)
        poster = self.root / "public" / result["movies"][0]["poster"].lstrip("/")
        self.assertTrue(poster.exists())
        unrelated = poster.parent / "unrelated-original.svg"
        unrelated.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        publish_catalog(catalog, self.manifest([]), out)
        self.assertEqual(json.loads(out.read_text())["movies"], [])
        self.assertFalse(poster.exists())
        self.assertTrue(unrelated.exists())

    def test_unknown_movie_clearance_rejected(self):
        catalog, movie = self.imported_catalog()
        rights = {"id": "does-not-exist", "distribution": "cleared", "evidence": "test", "links": [], "poster": {"status": "none"}}
        with self.assertRaises(CatalogError):
            publish_catalog(catalog, self.manifest([rights]), self.root / "public/movies.json")

    def test_rights_evidence_required(self):
        catalog, movie = self.imported_catalog()
        rights = {"id": movie["id"], "distribution": "cleared", "evidence": "", "links": [], "poster": {"status": "none"}}
        with self.assertRaises(CatalogError):
            publish_catalog(catalog, self.manifest([rights]), self.root / "public/movies.json")


class ValidationTests(unittest.TestCase):
    def movie(self):
        return {"id": "m-test", "title": "A Test", "year": 2020, "genres": ["Drama"], "synopsis": "An invented film.", "poster": None, "links": [], "sources": [], "rights": {"distribution": "cleared", "poster": "none", "evidence": "Synthetic test record"}}

    def catalog(self, movie):
        return {"schemaVersion": 1, "generatedAt": "2026-01-01T00:00:00Z", "kind": "public", "movies": [movie]}

    def test_accepts_valid_public_catalog(self):
        validate_catalog(self.catalog(self.movie()))

    def test_rejects_duplicate_ids(self):
        catalog = self.catalog(self.movie())
        catalog["movies"].append(self.movie())
        with self.assertRaises(CatalogError):
            validate_catalog(catalog)

    def test_rejects_executable_link_urls(self):
        movie = self.movie()
        movie["links"] = [{"label": "Unsafe", "quality": None, "url": "javascript:alert(1)", "size": None}]
        with self.assertRaises(CatalogError):
            validate_catalog(self.catalog(movie))

    def test_rejects_unapproved_distribution(self):
        movie = self.movie()
        movie["rights"]["distribution"] = "pending"
        with self.assertRaises(CatalogError):
            validate_catalog(self.catalog(movie))


class CliTests(ImporterCase):
    def cli(self, *arguments, check=True):
        result = subprocess.run([sys.executable, "-m", "importer", *map(str, arguments)], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_multi_channel_import_validate_publish_workflow(self):
        first = self.zip({"messages.html": self.message("1", 'Title: CLI Shared<br>Year: 2024<br>Genre: Drama<br><a href="https://example.com/first">1080p</a>')}, "first.zip")
        second = self.zip({"messages.html": self.message("2", 'Title: CLI Shared<br>Year: 2024<br>Genre: Drama<br><a href="https://example.com/second">720p</a>')}, "second.zip")
        private = self.root / "private"
        for channel, archive in (("one", first), ("two", second)):
            result = self.cli("import", archive, "--private-dir", private, "--channel-id", channel, "--channel-name", channel.title())
            self.assertEqual(json.loads(result.stdout)["status"], "private_pending_review")
            self.assertNotIn("CLI Shared", result.stdout)
        catalog = json.loads((private / "movies.json").read_text())
        self.assertEqual(len(catalog["movies"]), 1)
        self.cli("validate", private / "movies.json")
        manifest = self.root / "rights.json"
        manifest.write_text(json.dumps({"records": [{"id": catalog["movies"][0]["id"], "distribution": "cleared", "evidence": "Synthetic e2e fixture", "links": ["https://example.com/first"], "poster": {"status": "none"}}]}))
        out = self.root / "public/data/movies.json"
        result = self.cli("publish", "--private-dir", private, "--manifest", manifest, "--output", out)
        self.assertEqual(json.loads(result.stdout)["movies"], 1)
        self.cli("validate", out, "--public")
        public = json.loads(out.read_text())
        self.assertEqual([link["url"] for link in public["movies"][0]["links"]], ["https://example.com/first"])
        self.assertEqual({source["channelId"] for source in public["movies"][0]["sources"]}, {"one", "two"})

    def test_rejects_missing_archive_with_failure_exit_status(self):
        result = self.cli("import", self.root / "missing.zip", "--private-dir", self.root / "private", "--channel-id", "a", "--channel-name", "A", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not exist", result.stderr)


if __name__ == "__main__":
    unittest.main()
