"""Isolated acceptance checks for portable submission restore and bundle validation."""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from unittest import mock
from pathlib import Path

from tools import restore_submission


def make_root(parent: Path, name="package") -> Path:
    root = parent / name
    root.mkdir()
    shutil.copytree(Path(__file__).resolve().parents[1] / "app", root / "app",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (root / "config.example.json").write_text(json.dumps({
        "server": {"host": "127.0.0.1", "port": 8765},
        "llm": {"active": "offline", "profiles": {"offline": {"provider": "offline"}}},
    }), encoding="utf-8")
    asset = "submission-data/sources/library-1/original.txt"
    asset_path = root / asset
    asset_path.parent.mkdir(parents=True)
    raw = "제출용 원문 내용입니다.".encode("utf-8")
    asset_path.write_bytes(raw)
    file_id = uuid.uuid5(uuid.NAMESPACE_URL, os.path.normcase(str(asset_path))).hex
    source = {
        "id": "source-1", "library_id": "library-1", "file_id": file_id,
        "title": "기관 지침", "sha256": hashlib.sha256(raw).hexdigest(),
        "units": [{"text": "제출용 원문 내용입니다.", "loc": "1쪽"}],
        "limited": False, "kind": "기관 지침", "institution": "시험기관",
        "effective_date": "", "registered_at": "2026-10-20T00:00:00+00:00",
        "asset": asset, "enabled": 1, "library_name": "제출용 자료함",
    }
    bundle = {"format": 1, "sources": [source]}
    (root / "submission-data/knowledge.json").write_text(
        json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    return root


def read_source(root: Path):
    with closing(sqlite3.connect(root / "data/folders.db")) as connection:
        enabled, payload = connection.execute(
            "SELECT enabled,payload FROM knowledge_sources WHERE id='source-1'"
        ).fetchone()
        library = json.loads(connection.execute(
            "SELECT payload FROM libraries WHERE id='library-1'"
        ).fetchone()[0])
    return enabled, json.loads(payload), library


def rescan(root: Path):
    from app import folders
    with closing(sqlite3.connect(root / "data/folders.db")) as connection:
        version = connection.execute(
            "SELECT version FROM libraries WHERE id='library-1'"
        ).fetchone()[0]
    with mock.patch.object(folders, "DB_PATH", root / "data/folders.db"):
        return folders.scan("library-1", folders.Scan(version=version))


class PortableSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_restore_preserves_source_identity_hash_units_and_current_source(self):
        root = make_root(self.base)
        result = restore_submission.restore(root)
        self.assertEqual(result["status"], "restored")
        enabled, source, library = read_source(root)
        self.assertEqual(enabled, 1)
        self.assertEqual(source["id"], "source-1")
        self.assertEqual(source["sha256"], hashlib.sha256((root / source["path"]).read_bytes()).hexdigest())
        self.assertEqual(source["units"], [{"text": "제출용 원문 내용입니다.", "loc": "1쪽"}])
        self.assertEqual(library["files"][source["file_id"]]["units"], source["units"])
        from app.knowledge import current_source
        self.assertTrue(current_source(source))
        rescanned = rescan(root)
        self.assertIn(source["file_id"], {item["id"] for item in rescanned["files"]})
        self.assertEqual(read_source(root)[1]["file_id"], source["file_id"])

    def test_rerun_preserves_user_config_and_enabled_change(self):
        root = make_root(self.base)
        restore_submission.restore(root)
        config = {"server": {"port": 9012}, "llm": {"active": "user-model"}}
        (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
        with closing(sqlite3.connect(root / "data/folders.db")) as connection:
            connection.execute("UPDATE knowledge_sources SET enabled=0 WHERE id='source-1'")
            connection.commit()
        self.assertEqual(restore_submission.restore(root)["status"], "already_restored")
        self.assertEqual(json.loads((root / "config.json").read_text(encoding="utf-8")), config)
        self.assertEqual(read_source(root)[0], 0)

    def test_install_marker_with_missing_database_is_not_treated_as_restored(self):
        root = make_root(self.base)
        restore_submission.restore(root)
        database = root / "data/folders.db"
        marker = root / "data/submission-installation.json"
        database.unlink()
        self.assertTrue(marker.exists())
        with self.assertRaises(ValueError):
            restore_submission.restore(root)
        self.assertFalse(database.exists())
        self.assertTrue(marker.exists())

    def test_moved_package_rebases_owned_paths_and_keeps_user_roots_and_data(self):
        old = make_root(self.base, "old-package")
        restore_submission.restore(old)
        user_root = self.base / "my-documents"
        user_root.mkdir()
        (user_root / "memo.txt").write_text("user-owned", encoding="utf-8")
        custom_config = {"custom": "kept", "llm": {"active": "chosen"}}
        (old / "config.json").write_text(json.dumps(custom_config), encoding="utf-8")
        with closing(sqlite3.connect(old / "data/folders.db")) as connection:
            connection.execute("BEGIN")
            row = connection.execute("SELECT payload FROM libraries WHERE id='library-1'").fetchone()
            library = json.loads(row[0])
            library["roots"].append(str(user_root))
            connection.execute("UPDATE libraries SET payload=? WHERE id='library-1'",
                               (json.dumps(library, ensure_ascii=False),))
            connection.commit()
        moved = self.base / "moved-package"
        shutil.copytree(old, moved)
        self.assertEqual(restore_submission.restore(moved)["status"], "rebased")
        enabled, source, library = read_source(moved)
        self.assertEqual(enabled, 1)
        self.assertEqual(Path(source["path"]), moved / "submission-data/sources/library-1/original.txt")
        self.assertIn(str(user_root), library["roots"])
        self.assertTrue((user_root / "memo.txt").exists())
        self.assertEqual(json.loads((moved / "config.json").read_text(encoding="utf-8")), custom_config)
        from app.knowledge import current_source
        self.assertTrue(current_source(source))
        rescanned = rescan(moved)
        self.assertIn(source["file_id"], {item["id"] for item in rescanned["files"]})
        self.assertEqual(read_source(moved)[1]["file_id"], source["file_id"])

    def test_user_root_inside_old_install_survives_rebase_and_keeps_its_file(self):
        old = make_root(self.base, "old-install")
        restore_submission.restore(old)
        user_root = old / "user-docs"
        user_root.mkdir()
        user_file = user_root / "memo.txt"
        user_file.write_text("user-owned", encoding="utf-8")
        with closing(sqlite3.connect(old / "data/folders.db")) as connection:
            row = connection.execute("SELECT payload FROM libraries WHERE id='library-1'").fetchone()
            library = json.loads(row[0])
            library["roots"].append(str(user_root))
            connection.execute("UPDATE libraries SET payload=? WHERE id='library-1'",
                               (json.dumps(library, ensure_ascii=False),))
            connection.commit()
        moved = self.base / "moved-install"
        shutil.copytree(old, moved)
        self.assertEqual(restore_submission.restore(moved)["status"], "rebased")
        _, _, library = read_source(moved)
        expected_root = moved / "user-docs"
        self.assertIn(str(expected_root), library["roots"])
        self.assertTrue((expected_root / "memo.txt").is_file())
        self.assertEqual((expected_root / "memo.txt").read_text(encoding="utf-8"), "user-owned")

    def test_rebases_added_sources_and_new_libraries_after_package_move(self):
        old = make_root(self.base, "old-package-with-user-data")
        restore_submission.restore(old)
        user_root = old / "data/userdocs"
        user_root.mkdir(parents=True)
        added_source_path = user_root / "registered-after-install.txt"
        added_source_raw = b"registered after installation"
        added_source_path.write_bytes(added_source_raw)
        new_library_file = user_root / "new-library-file.txt"
        new_library_raw = b"new library user file"
        new_library_file.write_bytes(new_library_raw)

        added_source = {
            "id": "user-source-1", "library_id": "library-1", "file_id": "user-file-1",
            "title": "사용자 추가 자료", "path": str(added_source_path),
            "sha256": hashlib.sha256(added_source_raw).hexdigest(),
            "units": [{"text": "registered after installation", "loc": "1행"}],
            "limited": False, "kind": "기관 지침", "institution": "시험기관",
            "effective_date": "", "registered_at": "2026-10-21T00:00:00+00:00",
        }
        bundled_file = {
            "id": "user-file-1", "name": added_source_path.name, "path": str(added_source_path),
            "root": str(user_root), "sha256": added_source["sha256"], "size": len(added_source_raw),
            "mtime_ns": added_source_path.stat().st_mtime_ns, "units": added_source["units"],
            "present": True, "limited": False,
        }
        user_file = {
            "id": "new-library-file-1", "name": new_library_file.name, "path": str(new_library_file),
            "root": str(user_root), "sha256": hashlib.sha256(new_library_raw).hexdigest(),
            "size": len(new_library_raw), "mtime_ns": new_library_file.stat().st_mtime_ns,
            "units": [{"text": "new library user file", "loc": "1행"}], "present": True,
            "limited": False,
        }
        with closing(sqlite3.connect(old / "data/folders.db")) as connection:
            row = connection.execute("SELECT payload FROM libraries WHERE id='library-1'").fetchone()
            bundled_library = json.loads(row[0])
            bundled_library["roots"].append(str(user_root))
            bundled_library["files"]["user-file-1"] = bundled_file
            connection.execute("UPDATE libraries SET payload=? WHERE id='library-1'",
                               (json.dumps(bundled_library, ensure_ascii=False),))
            new_library = {
                "id": "user-library-1", "name": "사용자 자료함", "roots": [str(user_root)],
                "files": {"new-library-file-1": user_file}, "projects": {}, "warnings": [],
            }
            connection.execute("INSERT INTO libraries VALUES(?,?,?)",
                               ("user-library-1", 1, json.dumps(new_library, ensure_ascii=False)))
            connection.execute("INSERT INTO knowledge_sources VALUES(?,?,?,?,?)",
                               ("user-source-1", "library-1", "user-file-1", 1,
                                json.dumps(added_source, ensure_ascii=False)))
            connection.commit()

        moved = self.base / "moved-package-with-user-data"
        shutil.copytree(old, moved)
        self.assertEqual(restore_submission.restore(moved)["status"], "rebased")
        with closing(sqlite3.connect(moved / "data/folders.db")) as connection:
            library_rows = connection.execute("SELECT id,payload FROM libraries").fetchall()
            source_rows = connection.execute("SELECT id,payload FROM knowledge_sources").fetchall()
        for library_id, payload in library_rows:
            library = json.loads(payload)
            for root_path in library.get("roots", []):
                if Path(root_path).is_relative_to(old):
                    self.fail(f"{library_id} root still points into old package: {root_path}")
                if Path(root_path).is_relative_to(moved):
                    self.assertTrue(Path(root_path).exists(), root_path)
            for file in library.get("files", {}).values():
                for field in ("path", "root"):
                    value = file.get(field)
                    if value and Path(value).is_relative_to(old):
                        self.fail(f"{library_id} {field} still points into old package: {value}")
                    if value and Path(value).is_relative_to(moved):
                        self.assertTrue(Path(value).is_dir() if field == "root" else Path(value).is_file(), value)
        rebased_source = None
        for source_id, payload in source_rows:
            source = json.loads(payload)
            if Path(source.get("path", "")).is_relative_to(old):
                self.fail(f"{source_id} still points into old package: {source['path']}")
            if source_id == "user-source-1":
                rebased_source = source
        self.assertIsNotNone(rebased_source)
        expected_source = moved / "data/userdocs/registered-after-install.txt"
        self.assertEqual(Path(rebased_source["path"]), expected_source)
        self.assertTrue(expected_source.is_file())

        # Removing the original user file proves the relocated registration reads the new copy.
        added_source_path.unlink()
        from app.knowledge import current_source
        self.assertTrue(current_source(rebased_source))

    def test_safe_path_rejects_escape_and_damaged_asset_causes_no_restore_changes(self):
        root = make_root(self.base)
        for name in ("../outside.txt", "submission-data/../../outside.txt", r"C:\outside.txt"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                restore_submission.safe_path(root, name)
        asset = root / "submission-data/sources/library-1/original.txt"
        asset.write_text("corrupt", encoding="utf-8")
        with self.assertRaises(ValueError):
            restore_submission.restore(root)
        self.assertFalse((root / "data/folders.db").exists())
        self.assertFalse((root / "data/submission-installation.json").exists())

    def test_existing_database_is_refused_without_modification(self):
        root = make_root(self.base)
        data = root / "data"
        data.mkdir()
        db = data / "folders.db"
        db.write_bytes(b"user-owned-database")
        with self.assertRaises(ValueError):
            restore_submission.restore(root)
        self.assertEqual(db.read_bytes(), b"user-owned-database")
        self.assertFalse((data / "submission-installation.json").exists())

    def test_modified_bundle_is_refused_after_install(self):
        root = make_root(self.base)
        restore_submission.restore(root)
        bundle_path = root / "submission-data/knowledge.json"
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        bundle["sources"][0]["title"] = "changed bundle"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        before = (root / "data/folders.db").read_bytes()
        with self.assertRaises(ValueError):
            restore_submission.restore(root)
        self.assertEqual((root / "data/folders.db").read_bytes(), before)

    def test_checked_bundle_returns_verified_bundle_and_digest(self):
        root = make_root(self.base)
        bundle, digest = restore_submission.checked_bundle(root)
        self.assertEqual(bundle["sources"][0]["id"], "source-1")
        self.assertEqual(digest, hashlib.sha256((root / "submission-data/knowledge.json").read_bytes()).hexdigest())

    def test_duplicate_path_matches_are_remapped_deterministically_without_collision(self):
        from app.folders import propose
        path = str(self.base / "same.txt")
        old = {key: {"id": key, "path": path, "sha256": "same", "size": 1,
                     "mtime_ns": 1, "present": False}
               for key in ("z-old", "a-old")}
        def item(key):
            return {"id": key, "path": path, "name": "same.txt", "root": str(self.base),
                    "size": 1, "mtime_ns": 1, "sha256": "same", "units": [],
                    "present": True, "status": "본문 확인",
                    "clues": {"eligible": False, "common": False, "reason": "확인 필요"}}
        incoming = {"z-new": item("z-new"), "a-new": item("a-new")}
        library = {"files": old, "projects": {}}
        propose(library, incoming, [])
        self.assertEqual(list(incoming), ["a-old", "z-old"])
        self.assertEqual({value["id"] for value in incoming.values()}, {"a-old", "z-old"})


if __name__ == "__main__":
    unittest.main()
