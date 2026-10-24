import unittest

from tools.audit_question_relevance import evaluate_case


class QuestionAuditEvaluatorTest(unittest.TestCase):
    sha = "a" * 64
    text = "제1조 지급은 확인 후 처리한다. 필요한 증빙을 보관한다."
    sources = {sha: text}

    def case(self, **overrides):
        value = {"id": "sample", "category": "unit", "question": "어떻게 처리하나요?", "outcome": "answer",
                 "allow_articles": ["제1조"], "require_articles": ["제1조"], "facts": ["필요한 증빙을 보관한다."]}
        value.update(overrides)
        return value

    def reply(self, *, article="제1조", rule="approved", answer="[1] 지급은 확인 후 처리한다.", ref=1,
              support="지급은 확인 후 처리한다."):
        evidence = {"sha256": self.sha, "quote": self.text, "text": self.text,
                    "official": {"article": article}}
        return {"mode": "source_search", "answer": answer, "knowledge": {
                "evidence": [evidence], "tree": {"kind": "summary", "rule_id": rule, "branches": [{"items": [
                    {"ref": ref, "support_quotes": [support], "text": "결재 전에 증빙을 확인한다."}]}]}}}

    def test_valid_answer_passes(self):
        checked = evaluate_case(self.case(allow_rules=["approved"]), self.reply(), self.sources)
        self.assertTrue(checked["passed"], checked["failures"])

    def test_unknown_tree_reference_fails(self):
        checked = evaluate_case(self.case(), self.reply(ref=8), self.sources)
        self.assertTrue(any("invalid ref" in failure for failure in checked["failures"]))

    def test_wrong_article_fails(self):
        checked = evaluate_case(self.case(), self.reply(article="제9조"), self.sources)
        self.assertTrue(any("outside allow_articles" in failure for failure in checked["failures"]))
        self.assertTrue(any("required article" in failure for failure in checked["failures"]))

    def test_nonofficial_evidence_fails_allow_articles(self):
        reply = self.reply()
        reply["knowledge"]["evidence"][0].pop("official")
        checked = evaluate_case(self.case(), reply, self.sources)
        self.assertTrue(any("outside allow_articles" in failure for failure in checked["failures"]))

    def test_wrong_summary_fails(self):
        checked = evaluate_case(self.case(allow_rules=["expected"]), self.reply(rule="unexpected"), self.sources)
        self.assertTrue(any("outside allow_rules" in failure for failure in checked["failures"]))

    def test_missing_fact_fails(self):
        checked = evaluate_case(self.case(facts=["없는 문구"]), self.reply(), self.sources)
        self.assertTrue(any("source facts missing" in failure for failure in checked["failures"]))

    def test_source_fact_does_not_satisfy_answer_fact(self):
        case = self.case(answer_facts=["필요한 증빙을 보관한다."])
        checked = evaluate_case(case, self.reply(), self.sources)
        self.assertTrue(any("answer facts missing" in failure for failure in checked["failures"]))

    def test_answer_fact_must_appear_in_displayed_answer(self):
        case = self.case(answer_facts=["필요한 증빙을 보관한다."])
        answer = "[1] 지급은 확인 후 처리한다. 필요한 증빙을 보관한다."
        checked = evaluate_case(case, self.reply(answer=answer), self.sources)
        self.assertFalse(any("answer facts missing" in failure for failure in checked["failures"]))
        self.assertTrue(checked["passed"], checked["failures"])

    def test_blank_answer_fails(self):
        checked = evaluate_case(self.case(), self.reply(answer="  \n"), self.sources)
        self.assertTrue(any("nonblank displayed answer" in failure for failure in checked["failures"]))

    def test_summary_facts_pass_when_present_in_tree_text(self):
        checked = evaluate_case(self.case(summary_facts=["결재 전에 증빙을 확인한다."]), self.reply(), self.sources)
        self.assertTrue(checked["passed"], checked["failures"])

    def test_summary_facts_fail_when_missing_from_tree_text(self):
        checked = evaluate_case(self.case(summary_facts=["누락된 요약 문구"]), self.reply(), self.sources)
        self.assertTrue(any("summary facts missing" in failure for failure in checked["failures"]))

    def test_require_rules_pass_and_fail(self):
        passed = evaluate_case(self.case(require_rules=["approved"]), self.reply(rule="approved"), self.sources)
        failed = evaluate_case(self.case(require_rules=["required"]), self.reply(rule="approved"), self.sources)
        self.assertTrue(passed["passed"], passed["failures"])
        self.assertTrue(any("required summary rule" in failure for failure in failed["failures"]))


if __name__ == "__main__":
    unittest.main()
