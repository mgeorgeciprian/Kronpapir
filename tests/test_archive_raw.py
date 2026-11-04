"""Tests for archive_articles.archive_raw(). All data lives in a temp directory."""

import json
import os
import sys
import tarfile
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import archive_articles  # noqa: E402

OLD_MTIME = time.time() - 10 * 86400
MONTH = datetime.fromtimestamp(OLD_MTIME).strftime("%Y-%m")


class ArchiveRawTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.articles = root / "articles"
        self.archives = root / "archives"
        self.processed = root / "processed"
        for d in (self.articles, self.archives, self.processed):
            d.mkdir()
        for name, value in (("ARTICLES_DIR", self.articles),
                            ("ARCHIVE_DIR", self.archives),
                            ("PROCESSED_DIR", self.processed)):
            patcher = mock.patch.object(archive_articles, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, source, name, payload):
        path = self.articles / source / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        os.utime(path, (OLD_MTIME, OLD_MTIME))
        return path

    def archive_path(self, source="src"):
        return self.archives / f"raw_{source}_{MONTH}.tar.gz"

    def read_archive(self, path=None):
        """Return (member names in order, {name: decoded json})."""
        with tarfile.open(path or self.archive_path(), "r:gz") as tar:
            names = tar.getnames()
            return names, {m.name: json.load(tar.extractfile(m)) for m in tar.getmembers()}

    def archive_dir_names(self):
        return sorted(p.name for p in self.archives.iterdir())

    def assert_failed_safely(self, original_bytes, originals):
        """Archive bytes untouched, originals kept, nothing but the archive left."""
        self.assertEqual(self.archive_path().read_bytes(), original_bytes)
        for path in originals:
            self.assertTrue(path.exists(), path)
        self.assertEqual(self.archive_dir_names(), [self.archive_path().name])

    def test_first_archive_creation(self):
        a = self.write("src", "a.json", {"id": "a"})
        b = self.write("src", "b.json", {"id": "b"})

        self.assertEqual(archive_articles.archive_raw()[0], 2)

        names, data = self.read_archive()
        self.assertEqual(sorted(names), ["src/a.json", "src/b.json"])
        self.assertEqual(data["src/a.json"], {"id": "a"})
        self.assertFalse(a.exists())
        self.assertFalse(b.exists())
        self.assertEqual(self.archive_dir_names(), [self.archive_path().name])

    def test_second_run_appends_and_old_members_stay_readable(self):
        self.write("src", "old.json", {"id": "old"})
        archive_articles.archive_raw()
        new = self.write("src", "new.json", {"id": "new"})

        self.assertEqual(archive_articles.archive_raw()[0], 1)

        names, data = self.read_archive()
        self.assertEqual(sorted(names), ["src/new.json", "src/old.json"])
        self.assertEqual(data["src/old.json"], {"id": "old"})
        self.assertEqual(data["src/new.json"], {"id": "new"})
        self.assertFalse(new.exists())
        self.assertEqual(self.archive_dir_names(), [self.archive_path().name])

    def test_third_run_keeps_every_member(self):
        for i in range(3):
            self.write("src", f"{i}.json", {"id": i})
            archive_articles.archive_raw()
        names, data = self.read_archive()
        self.assertEqual(sorted(names), ["src/0.json", "src/1.json", "src/2.json"])
        self.assertEqual(data["src/0.json"], {"id": 0})

    def test_duplicate_arcname_new_file_wins(self):
        self.write("src", "dup.json", {"version": "old"})
        self.write("src", "other.json", {"id": "other"})
        archive_articles.archive_raw()
        dup = self.write("src", "dup.json", {"version": "new"})

        archive_articles.archive_raw()

        names, data = self.read_archive()
        self.assertEqual(names.count("src/dup.json"), 1)
        self.assertEqual(sorted(names), ["src/dup.json", "src/other.json"])
        self.assertEqual(data["src/dup.json"], {"version": "new"})
        self.assertFalse(dup.exists())

    def test_corrupt_existing_archive_is_left_alone(self):
        original = self.write("src", "a.json", {"id": "a"})
        for label, content in (("garbage", b"this is not a gzip file at all"),
                               ("empty", b"")):
            with self.subTest(label):
                self.archive_path().write_bytes(content)
                self.assertEqual(archive_articles.archive_raw()[0], 0)
                self.assert_failed_safely(content, [original])

    def test_truncated_existing_archive_is_left_alone(self):
        self.write("src", "old.json", {"id": "old", "pad": os.urandom(40000).hex()})
        archive_articles.archive_raw()
        truncated = self.archive_path().read_bytes()[:-2000]
        self.archive_path().write_bytes(truncated)
        original = self.write("src", "new.json", {"id": "new"})

        self.assertEqual(archive_articles.archive_raw()[0], 0)

        self.assert_failed_safely(truncated, [original])

    def test_failed_group_does_not_stop_next_group(self):
        self.archive_path("bad").write_bytes(b"corrupt")
        bad = self.write("bad", "a.json", {"id": "a"})
        good = self.write("good", "b.json", {"id": "b"})

        self.assertEqual(archive_articles.archive_raw()[0], 1)

        self.assertTrue(bad.exists())
        self.assertFalse(good.exists())
        self.assertEqual(self.read_archive(self.archive_path("good"))[0], ["good/b.json"])
        self.assertEqual(self.archive_path("bad").read_bytes(), b"corrupt")

    def test_replace_failure_keeps_everything(self):
        self.write("src", "old.json", {"id": "old"})
        archive_articles.archive_raw()
        before = self.archive_path().read_bytes()
        original = self.write("src", "new.json", {"id": "new"})

        with mock.patch.object(archive_articles.os, "replace", side_effect=OSError("boom")):
            self.assertEqual(archive_articles.archive_raw()[0], 0)

        self.assert_failed_safely(before, [original])

    def test_verification_failure_keeps_everything(self):
        self.write("src", "old.json", {"id": "old"})
        archive_articles.archive_raw()
        before = self.archive_path().read_bytes()
        original = self.write("src", "new.json", {"id": "new"})

        with mock.patch.object(tarfile.TarFile, "getnames", return_value=["wrong"]):
            self.assertEqual(archive_articles.archive_raw()[0], 0)

        self.assert_failed_safely(before, [original])

    def test_first_creation_failure_leaves_no_partial_archive(self):
        original = self.write("src", "a.json", {"id": "a"})

        with mock.patch.object(tarfile.TarFile, "add", side_effect=OSError("boom")):
            self.assertEqual(archive_articles.archive_raw()[0], 0)

        self.assertTrue(original.exists())
        self.assertEqual(self.archive_dir_names(), [])

    def test_temp_name_is_not_counted_by_archive_globs(self):
        self.write("src", "a.json", {"id": "a"})
        seen = {}
        real_replace = os.replace

        def spy(src, dst):
            seen["glob"] = sorted(p.name for p in self.archives.glob("*.tar.gz"))
            seen["raw_glob"] = sorted(p.name for p in self.archives.glob("raw_*"))
            seen["src"] = Path(src)
            real_replace(src, dst)

        with mock.patch.object(archive_articles.os, "replace", side_effect=spy):
            archive_articles.archive_raw()

        self.assertEqual(seen["src"].parent, self.archives)
        self.assertEqual(seen["glob"], [])
        self.assertEqual(seen["raw_glob"], [])

    def test_existing_archive_permissions_are_preserved(self):
        self.write("src", "old.json", {"id": "old"})
        archive_articles.archive_raw()
        os.chmod(self.archive_path(), 0o640)
        self.write("src", "new.json", {"id": "new"})

        archive_articles.archive_raw()

        self.assertEqual(self.archive_path().stat().st_mode & 0o7777, 0o640)

    def test_dry_run_changes_nothing(self):
        self.write("src", "old.json", {"id": "old"})
        archive_articles.archive_raw()
        before = self.archive_path().read_bytes()
        new = self.write("src", "new.json", {"id": "new"})
        fresh = self.write("other", "x.json", {"id": "x"})

        count, _ = archive_articles.archive_raw(dry_run=True)

        self.assertEqual(count, 2)
        self.assertEqual(self.archive_path().read_bytes(), before)
        self.assertEqual(self.archive_dir_names(), [self.archive_path().name])
        self.assertTrue(new.exists())
        self.assertTrue(fresh.exists())

    def test_processed_files_are_never_archived(self):
        kept = self.write("src", "batch_processed.json", {"id": "p"})
        self.write("src", "a.json", {"id": "a"})

        archive_articles.archive_raw()
        self.assertEqual(self.read_archive()[0], ["src/a.json"])

        self.write("src", "b.json", {"id": "b"})
        archive_articles.archive_raw()

        self.assertEqual(sorted(self.read_archive()[0]), ["src/a.json", "src/b.json"])
        self.assertTrue(kept.exists())


if __name__ == "__main__":
    unittest.main()
