"""Isolated checks for portable submission documentation and its manifest."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import build_portable_submission


class SubmissionBuildDocsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "source"
        self.root.mkdir()
        for directory in ("app", "static", "sample_data", "reference_data", "tests", "tools", "docs"):
            (self.root / directory).mkdir()
        for name in ("requirements.txt", "requirements-travel.lock.txt", "config.example.json",
                     "install-submission.bat", "start-submission.bat"):
            (self.root / name).write_text("stub", encoding="utf-8")
        self.wheels = self.base / "wheels"
        self.wheels.mkdir()
        (self.wheels / "dummy.whl").write_bytes(b"wheel")

    def tearDown(self):
        self.temp.cleanup()

    def build_with_guides(self, guides):
        for relative, content in guides.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        dest = self.base / "candidate"
        with mock.patch.object(build_portable_submission, "export_knowledge", return_value={"sources": []}):
            manifest = build_portable_submission.build(dest, self.wheels, self.root)
        return dest, manifest

    def test_v45_guide_precedes_v44_and_root_and_both_docs_are_manifested(self):
        dest, manifest = self.build_with_guides({
            "docs/다른PC_제출패키지_구동안내_v45.txt": "v45 guide",
            "docs/다른PC_제출패키지_구동안내_v44.txt": "v44 guide",
            "먼저읽기.txt": "root guide",
        })
        self.assertEqual((dest / "먼저읽기.txt").read_text(encoding="utf-8"), "v45 guide")
        self.assertIn("검증보고서_v45.txt", (dest / "검증결과바로가기.txt").read_text(encoding="utf-8"))
        self.assertIn("최종검증요약_v45.json", (dest / "검증결과바로가기.txt").read_text(encoding="utf-8"))
        self.assertIn("archive --evidence", (dest / "검증결과바로가기.txt").read_text(encoding="utf-8"))
        for name in ("먼저읽기.txt", "검증결과바로가기.txt"):
            self.assertEqual(manifest["files"][name], hashlib.sha256((dest / name).read_bytes()).hexdigest())

    def test_v44_guide_is_fallback(self):
        dest, _ = self.build_with_guides({"docs/다른PC_제출패키지_구동안내_v44.txt": "v44 guide"})
        self.assertEqual((dest / "먼저읽기.txt").read_text(encoding="utf-8"), "v44 guide")

    def test_v53_guide_and_evidence_links_replace_previous_release(self):
        dest, manifest = self.build_with_guides({
            "docs/다른PC_제출패키지_구동안내_v53.txt": "v53 guide",
            "docs/다른PC_제출패키지_구동안내_v45.txt": "v45 guide",
        })
        self.assertEqual((dest / "먼저읽기.txt").read_text(encoding="utf-8"), "v53 guide")
        links = (dest / "검증결과바로가기.txt").read_text(encoding="utf-8")
        self.assertIn("검증보고서_v53.txt", links)
        self.assertIn("최종검증요약_v53.json", links)
        self.assertNotIn("v45", links)
        self.assertEqual(manifest["release_version"], "v53")
        for name in ("먼저읽기.txt", "검증결과바로가기.txt"):
            self.assertEqual(manifest["files"][name], hashlib.sha256((dest / name).read_bytes()).hexdigest())

    def test_v54_guide_and_evidence_links_precede_previous_releases(self):
        dest, manifest = self.build_with_guides({
            "docs/다른PC_제출패키지_구동안내_v54.txt": "v54 guide",
            "docs/다른PC_제출패키지_구동안내_v53.txt": "v53 guide",
            "docs/다른PC_제출패키지_구동안내_v45.txt": "v45 guide",
        })
        self.assertEqual((dest / "먼저읽기.txt").read_text(encoding="utf-8"), "v54 guide")
        links = (dest / "검증결과바로가기.txt").read_text(encoding="utf-8")
        self.assertIn("검증보고서_v54.txt", links)
        self.assertIn("최종검증요약_v54.json", links)
        self.assertIn("archive --evidence", links)
        self.assertNotIn("v53", links)
        self.assertNotIn("v45", links)
        self.assertEqual(manifest["release_version"], "v54")
        self.assertEqual(
            manifest["files"]["먼저읽기.txt"],
            hashlib.sha256((dest / "먼저읽기.txt").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["files"]["검증결과바로가기.txt"],
            hashlib.sha256((dest / "검증결과바로가기.txt").read_bytes()).hexdigest(),
        )

    def test_v55_guide_and_evidence_links_precede_previous_releases(self):
        dest, manifest = self.build_with_guides({
            "docs/다른PC_제출패키지_구동안내_v55.txt": "v55 guide",
            "docs/다른PC_제출패키지_구동안내_v54.txt": "v54 guide",
            "docs/다른PC_제출패키지_구동안내_v53.txt": "v53 guide",
        })
        self.assertEqual((dest / "먼저읽기.txt").read_text(encoding="utf-8"), "v55 guide")
        links = (dest / "검증결과바로가기.txt").read_text(encoding="utf-8")
        self.assertIn("검증보고서_v55.txt", links)
        self.assertIn("최종검증요약_v55.json", links)
        self.assertIn("archive --evidence", links)
        self.assertNotIn("v54", links)
        self.assertNotIn("v53", links)
        self.assertEqual(manifest["release_version"], "v55")
        for name in ("먼저읽기.txt", "검증결과바로가기.txt"):
            self.assertEqual(
                manifest["files"][name],
                hashlib.sha256((dest / name).read_bytes()).hexdigest(),
            )

    def test_v57_guide_and_evidence_links_precede_previous_releases(self):
        dest, manifest = self.build_with_guides({
            "docs/다른PC_제출패키지_구동안내_v57.txt": "v57 guide",
            "docs/다른PC_제출패키지_구동안내_v55.txt": "v55 guide",
        })
        self.assertEqual((dest / "먼저읽기.txt").read_text(encoding="utf-8"), "v57 guide")
        links = (dest / "검증결과바로가기.txt").read_text(encoding="utf-8")
        self.assertIn("검증보고서_v57.txt", links)
        self.assertIn("최종검증요약_v57.json", links)
        self.assertIn("archive --evidence", links)
        self.assertNotIn("v55", links)
        self.assertEqual(manifest["release_version"], "v57")
        for name in ("먼저읽기.txt", "검증결과바로가기.txt"):
            self.assertEqual(
                manifest["files"][name],
                hashlib.sha256((dest / name).read_bytes()).hexdigest(),
            )

    def test_v61_guide_and_evidence_links_precede_previous_releases(self):
        dest, manifest = self.build_with_guides({
            "docs/다른PC_제출패키지_구동안내_v61.txt": "v61 guide",
            "docs/다른PC_제출패키지_구동안내_v57.txt": "v57 guide",
            "docs/다른PC_제출패키지_구동안내_v55.txt": "v55 guide",
        })
        self.assertEqual((dest / "먼저읽기.txt").read_text(encoding="utf-8"), "v61 guide")
        links = (dest / "검증결과바로가기.txt").read_text(encoding="utf-8")
        self.assertIn("검증보고서_v61.txt", links)
        self.assertIn("최종검증요약_v61.json", links)
        self.assertIn("archive --evidence", links)
        self.assertNotIn("v57", links)
        self.assertNotIn("v55", links)
        self.assertEqual(manifest["release_version"], "v61")
        for name in ("먼저읽기.txt", "검증결과바로가기.txt"):
            self.assertEqual(
                manifest["files"][name],
                hashlib.sha256((dest / name).read_bytes()).hexdigest(),
            )

    def test_v64_guide_and_evidence_links_precede_previous_releases(self):
        dest, manifest = self.build_with_guides({
            "docs/다른PC_제출패키지_구동안내_v64.txt": "v64 guide",
            "docs/다른PC_제출패키지_구동안내_v61.txt": "v61 guide",
        })
        self.assertEqual((dest / "먼저읽기.txt").read_text(encoding="utf-8"), "v64 guide")
        links = (dest / "검증결과바로가기.txt").read_text(encoding="utf-8")
        self.assertIn("검증보고서_v64.txt", links)
        self.assertIn("최종검증요약_v64.json", links)
        self.assertIn("archive --evidence", links)
        self.assertNotIn("v61", links)
        self.assertEqual(manifest["release_version"], "v64")
        for name in ("먼저읽기.txt", "검증결과바로가기.txt"):
            self.assertEqual(
                manifest["files"][name],
                hashlib.sha256((dest / name).read_bytes()).hexdigest(),
            )

    def test_v66_guide_and_evidence_links_precede_previous_releases(self):
        dest, manifest = self.build_with_guides({
            "docs/다른PC_제출패키지_구동안내_v66.txt": "v66 guide",
            "docs/다른PC_제출패키지_구동안내_v64.txt": "v64 guide",
            "docs/다른PC_제출패키지_구동안내_v61.txt": "v61 guide",
        })
        self.assertEqual((dest / "먼저읽기.txt").read_text(encoding="utf-8"), "v66 guide")
        links = (dest / "검증결과바로가기.txt").read_text(encoding="utf-8")
        self.assertIn("검증보고서_v66.txt", links)
        self.assertIn("최종검증요약_v66.json", links)
        self.assertNotIn("v64", links)
        self.assertNotIn("v61", links)
        self.assertEqual(manifest["release_version"], "v66")

    def test_v67_guide_and_evidence_links_precede_previous_releases(self):
        dest, manifest = self.build_with_guides({
            "docs/다른PC_제출패키지_구동안내_v67.txt": "v67 guide",
            "docs/다른PC_제출패키지_구동안내_v66.txt": "v66 guide",
            "docs/다른PC_제출패키지_구동안내_v64.txt": "v64 guide",
        })
        self.assertEqual((dest / "먼저읽기.txt").read_text(encoding="utf-8"), "v67 guide")
        links = (dest / "검증결과바로가기.txt").read_text(encoding="utf-8")
        self.assertIn("검증보고서_v67.txt", links)
        self.assertIn("최종검증요약_v67.json", links)
        self.assertIn("archive --evidence", links)
        self.assertNotIn("v66", links)
        self.assertNotIn("v64", links)
        self.assertEqual(manifest["release_version"], "v67")
        for name in ("먼저읽기.txt", "검증결과바로가기.txt"):
            self.assertEqual(
                manifest["files"][name],
                hashlib.sha256((dest / name).read_bytes()).hexdigest(),
            )

    def test_v68_guide_and_evidence_links_precede_previous_releases(self):
        dest, manifest = self.build_with_guides({
            "docs/다른PC_제출패키지_구동안내_v68.txt": "v68 guide",
            "docs/다른PC_제출패키지_구동안내_v67.txt": "v67 guide",
            "docs/다른PC_제출패키지_구동안내_v66.txt": "v66 guide",
        })
        self.assertEqual((dest / "먼저읽기.txt").read_text(encoding="utf-8"), "v68 guide")
        links = (dest / "검증결과바로가기.txt").read_text(encoding="utf-8")
        self.assertIn("검증보고서_v68.txt", links)
        self.assertIn("최종검증요약_v68.json", links)
        self.assertIn("archive --evidence", links)
        self.assertNotIn("v67", links)
        self.assertNotIn("v66", links)
        self.assertEqual(manifest["release_version"], "v68")
        for name in ("먼저읽기.txt", "검증결과바로가기.txt"):
            self.assertEqual(
                manifest["files"][name],
                hashlib.sha256((dest / name).read_bytes()).hexdigest(),
            )

    def test_v69_guide_and_evidence_links_precede_previous_releases(self):
        dest, manifest = self.build_with_guides({
            "docs/다른PC_제출패키지_구동안내_v69.txt": "v69 guide",
            "docs/다른PC_제출패키지_구동안내_v68.txt": "v68 guide",
            "docs/다른PC_제출패키지_구동안내_v67.txt": "v67 guide",
        })
        self.assertEqual((dest / "먼저읽기.txt").read_text(encoding="utf-8"), "v69 guide")
        links = (dest / "검증결과바로가기.txt").read_text(encoding="utf-8")
        self.assertIn("검증보고서_v69.txt", links)
        self.assertIn("최종검증요약_v69.json", links)
        self.assertIn("archive --evidence", links)
        self.assertNotIn("v68", links)
        self.assertNotIn("v67", links)
        self.assertEqual(manifest["release_version"], "v69")

    def test_root_guide_is_fallback_when_docs_guides_are_missing(self):
        dest, _ = self.build_with_guides({"먼저읽기.txt": "root guide"})
        self.assertEqual((dest / "먼저읽기.txt").read_text(encoding="utf-8"), "root guide")


if __name__ == "__main__":
    unittest.main()
