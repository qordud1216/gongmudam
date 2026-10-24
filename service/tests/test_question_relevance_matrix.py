import json
import unittest

from tools.audit_question_relevance import ROOT, _run_cases
from tools.check_question_answers import DEFAULT_MANIFEST, load_sources


class QuestionRelevanceMatrixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.verified_sources, cls.manifest_problems = load_sources(DEFAULT_MANIFEST)
        cls.matrices = []
        for fixture in (ROOT / "reference_data" / "question_checks_v39.json",
                        ROOT / "reference_data" / "question_checks_v39_holdout.json"):
            cases = json.loads(fixture.read_text(encoding="utf-8"))
            results = _run_cases(cases, cls.verified_sources)
            cls.matrices.append((fixture.name, cases, results))

    def test_every_reviewed_case_passes(self):
        self.assertFalse(self.manifest_problems, self.manifest_problems)
        for fixture_name, cases, results in self.matrices:
            with self.subTest(fixture=fixture_name):
                failed = [
                    {"id": result.get("id"), "category": result.get("category"),
                     "mode": result.get("mode"), "articles": result.get("articles"),
                     "rules": result.get("rules"), "failures": result.get("failures")}
                    for result in results if not result.get("passed")
                ]
                self.assertEqual(len(results), len(cases), f"{fixture_name}: runner did not return one result per fixture case")
                self.assertEqual(failed, [], f"{fixture_name}: {json.dumps(failed, ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    unittest.main()
