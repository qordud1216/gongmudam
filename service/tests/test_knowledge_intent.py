import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import folders, knowledge, knowledge_intent, main


class KnowledgeIntentScopeTest(unittest.TestCase):
    def test_2026_school_memo_is_out_of_scope_for_2024_national_query(self):
        source = {"title": "학교 복무 안내", "institution": "교육청", "effective_date": "2026-01-01"}
        reason = knowledge_intent.scope_reason("2024년 국가공무원 병가 기준", source, "2026-10-20")
        self.assertTrue(reason)

    def test_reference_memos_do_not_establish_topic_rules_or_deadlines(self):
        deadline = {"title": "출장 정산 안내 메모", "kind": "참고자료",
                    "text": "출장 정산 기한은 다루지 않았고 별도 확인이 필요합니다."}
        taxi = {"title": "출장 택시비 검토 메모", "kind": "참고자료",
                "text": "택시비는 검토하지 않았고 기준도 정하지 않았습니다."}
        self.assertFalse(knowledge_intent.supports("travel_settlement", deadline))
        self.assertFalse(knowledge_intent.supports("travel_taxi", taxi))

    def test_broad_manual_title_can_support_family_care(self):
        hit = {"title": "인사업무편람", "kind": "업무편람",
               "text": "가족돌봄휴가는 연간 10일의 범위에서 신청할 수 있다."}
        self.assertTrue(knowledge_intent.supports("family_care", hit))

    def test_child_teacher_mention_does_not_set_employee_scope(self):
        source = {"title": "복무 안내", "institution": "일반기관"}
        reason = knowledge_intent.scope_reason("자녀 담임교사와 상담을 위한 휴가", source, "2026-10-20")
        self.assertEqual(reason, "")

    def test_education_office_teacher_query_matches_teacher_scope(self):
        query = "교육청 소속 교원 병가 기준"
        general = {"title": "복무 안내", "institution": "일반기관"}
        teacher = {"title": "교육청 소속 교원 복무편람", "institution": "교육청"}
        self.assertTrue(knowledge_intent.scope_reason(query, general, "2026-10-20"))
        self.assertEqual(knowledge_intent.scope_reason(query, teacher, "2026-10-20"), "")

    def test_uncovered_travel_deadline_returns_unavailable_without_fallback(self):
        with tempfile.TemporaryDirectory(prefix="knowledge-intent-") as temp_dir:
            with patch.object(folders, "DB_PATH", Path(temp_dir) / "folders.db"):
                folders.initialize()
                knowledge.initialize()
                with patch.object(knowledge, "sources", return_value=[]) as sources, \
                     patch.object(main.assistant, "ask") as assistant_ask, \
                     patch.object(knowledge.llm, "get_provider") as get_provider:
                    result = main.api_ask({"query": "출장 정산 기한", "today": "2026-10-20"})
                    self.assertEqual(result["mode"], "source_unavailable")
                    self.assertEqual(result["knowledge"]["evidence"], [])
                    sources.assert_called_once()
                    assistant_ask.assert_not_called()
                    get_provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
