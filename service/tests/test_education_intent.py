import unittest
from unittest.mock import patch

from app import education_intent, main


class EducationIntentTests(unittest.TestCase):
    def test_explicit_education_collection_variants(self):
        for query in (
            "직원 교육 참석자 모집해 주세요",
            "교육 희망자 신청을 취합하고 명단 정리",
            "연수 참가자 인원 조사 부탁해",
            "워크숍 수강생 모집",
            "교육 희망자 수합해줘",
            "교육 신청자 명단 만들어줘",
        ):
            with self.subTest(query=query):
                self.assertTrue(education_intent.is_education_collection_request(query))

    def test_non_collection_and_excluded_topics(self):
        for query in (
            "교육 여비 정산 방법",
            "교육 출장 교통비 환급",
            "교육 휴가 신청 방법",
            "교육 신청 절차가 어떻게 되나요?",
            "교육 참석자 명단을 확인하는 방법",
            "연가 희망자 조사",
            "교육 신청자 자격은?",
        ):
            with self.subTest(query=query):
                self.assertFalse(education_intent.is_education_collection_request(query))

    def test_action_added_to_each_api_ask_return_branch(self):
        found = {"hits": [], "registered_count": 0, "requires_basis": False,
                 "experiences": [], "excluded": []}
        ask_result = {"query": "교육 참석자 모집", "mode": "offline", "alternatives": [],
                      "cited": [], "related": [], "personal_notes": []}
        question='교육 참석자 모집 규정은?'
        with (patch.object(main.knowledge, "retrieve", return_value=dict(found)),
              patch.object(main.leave, "guide", return_value=None),
              patch.object(main.assistant, "ask", return_value=dict(ask_result))):
            result = main.api_ask({"query": question})
        self.assertEqual(result["task_action"], {"kind": "education_collection", "label": "이 업무 시작하기"})

        source_reply = {"mode": "source_search", "model": None, "answer": "답", "notice": "", "tree": {}}
        with (patch.object(main.knowledge, "retrieve", return_value={**found, "hits": ["hit"]}),
              patch.object(main.knowledge, "answer", return_value=source_reply)):
            result = main.api_ask({"query": question})
        self.assertEqual(result["task_action"]["kind"], "education_collection")

        with (patch.object(main.knowledge, "retrieve", return_value=dict(found)),
              patch.object(main.leave, "guide", return_value={"query": "교육 참석자 모집", "mode": "leave_guide"})):
            result = main.api_ask({"query": question})
        self.assertEqual(result["task_action"]["kind"], "education_collection")

    def test_task_start_does_not_retrieve_unrelated_education_travel_law(self):
        with patch.object(main.knowledge,'retrieve',side_effect=AssertionError('unrelated law retrieval')):
            result=main.api_ask({'query':'각 부서의 교육 참석 희망자를 취합하고 누락과 중복을 확인해야 해요.'})
        self.assertEqual(result['mode'],'education_workflow')
        self.assertFalse(result['cited'])
        self.assertNotIn('2주',result['answer'])
        self.assertFalse(education_intent.is_start_request('교육 희망자 취합 근거 법령은?'))


if __name__ == "__main__":
    unittest.main()
