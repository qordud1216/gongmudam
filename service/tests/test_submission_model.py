import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.configure_submission_model import configure

ROOT = Path(__file__).resolve().parents[1]


class SubmissionModelConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copyfile(ROOT / "config.example.json", self.root / "config.example.json")

    def tearDown(self):
        self.temp.cleanup()

    def test_creates_config_from_example_and_activates_profile(self):
        cfg = configure(self.root, "submission_model", "HTTPS://localhost:8000/v1/", "demo")
        self.assertEqual(cfg["llm"]["active"], "submission_model")
        profile = cfg["llm"]["profiles"]["submission_model"]
        self.assertEqual(profile, {
            "provider": "openai_compatible", "base_url": "https://localhost:8000/v1",
            "model": "demo", "temperature": 0, "max_tokens": 700, "timeout": 180,
        })
        self.assertTrue((self.root / "config.json").exists())

    def test_preserves_other_configuration_and_profiles(self):
        before = json.loads((self.root / "config.example.json").read_text(encoding="utf-8"))
        (self.root / "config.json").write_text(json.dumps(before), encoding="utf-8")
        cfg = configure(self.root, "custom", "http://192.168.1.20:8000/v1", "model")
        self.assertEqual(cfg["server"], before["server"])
        self.assertEqual(cfg["llm"]["profiles"]["offline"], before["llm"]["profiles"]["offline"])
        self.assertEqual(cfg["llm"]["profiles"]["openai"], before["llm"]["profiles"]["openai"])

    def test_rejects_urls_with_credentials_query_fragment_or_missing_host(self):
        for url in ("ftp://example.com/v1", "http://user:pass@example.com/v1",
                    "http://example.com/v1?token=x", "http://example.com/v1#frag", "http:///v1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                configure(self.root, "profile", url, "model")

    def test_keeps_only_environment_variable_name_and_never_secret_value(self):
        with mock.patch.dict(os.environ, {"SERVICE_TOKEN": "secret-value"}):
            cfg = configure(self.root, "keyed", "http://localhost:8000/v1", "demo", "SERVICE_TOKEN")
        profile = cfg["llm"]["profiles"]["keyed"]
        self.assertEqual(profile["api_key_env"], "SERVICE_TOKEN")
        self.assertNotIn("api_key", profile)
        self.assertNotIn("secret-value", json.dumps(cfg))

    def test_json_object_flag_adds_response_format(self):
        cfg = configure(self.root, "json", "http://localhost:8000/v1", "demo", json_object=True)
        self.assertEqual(cfg["llm"]["profiles"]["json"]["extra_body"],
                         {"response_format": {"type": "json_object"}})


if __name__ == "__main__":
    unittest.main()
