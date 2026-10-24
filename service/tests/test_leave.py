"""새 휴가 질문은 종류·신분 확인부터 안내하고 숫자나 승인 결과를 만들지 않는다."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from app import leave,main


class LeaveGuideTest(unittest.TestCase):
    def test_general_leave_requires_choice(self):
        r=leave.guide('다음 주 휴가를 쓰고 싶어요')['leave_guide']
        self.assertIsNone(r['selected']);self.assertEqual(len(r['types']),6)
        self.assertIn('적용 신분',r['missing']);self.assertFalse(r['entitlement_confirmed'])

    def test_specific_six_types(self):
        for query,expected in [('연가 신청','annual'),('병가 신청','sick'),('공가 신청','official'),('특가 신청','special'),('대체휴무 신청','substitute'),('보상휴가 신청','conversion')]:
            with self.subTest(query=query): self.assertEqual(leave.guide(query)['leave_guide']['selected'],expected)

    def test_comparison_and_multiple_types_are_not_forced(self):
        for query in ['연가와 공가의 차이','휴가 종류','병가 연가 중 뭘 써야 하나요?']:
            self.assertIsNone(leave.guide(query)['leave_guide']['selected'])

    def test_family_illness_does_not_select_own_sick_leave(self):
        self.assertEqual(leave.guide('아이가 아파서 쉬려고요')['leave_guide']['selected'],'special')

    def test_clues_remain_candidates(self):
        g=leave.guide('예비군 훈련 참석해야 해요')['leave_guide']
        self.assertEqual(g['selected'],'official');self.assertEqual(g['selection'],'candidate')
        self.assertIn('자동 공가',g['questions'][1])

    def test_user_choice_and_context(self):
        g=leave.guide('휴가 종류', 'special',{'personnel':'local','work_pattern':'shift','subtype':'경조사'})['leave_guide']
        self.assertEqual(g['selection'],'user');self.assertEqual(g['missing'],[])
        self.assertIn('국가공무원 자료는 비교 참고자료',g['scope'])
        self.assertFalse(g['entitlement_confirmed'])
        self.assertTrue(any('결혼·입양·사망' in q for q in g['questions']))

    def test_fire_not_inferred_as_local(self):
        g=leave.guide('대체휴무','substitute',{'personnel':'fire','work_pattern':'shift'})['leave_guide']
        self.assertIn('소방공무원',g['scope']);self.assertIn('별도로',g['scope'])

    def test_other_personnel_not_auto_applied(self):
        g=leave.guide('병가',context={'personnel':'other'})['leave_guide']
        self.assertIn('자동 적용하지',g['scope'])

    def test_invalid_values_are_rejected(self):
        for kind,context in [('invalid',None),([],None),('sick',{'personnel':[]}),('sick',{'personnel':'<script>'}),('special',{'subtype':'임의 사유'}),('annual',{'work_pattern':'invalid'})]:
            with self.assertRaises(ValueError): leave.guide('휴가',kind,context)

    def test_non_leave_is_unchanged(self):
        for q in ['부산 출장 여비 정산','사무용품 구매','명절휴가비 지급 기준','휴무일 출장 여비 정산']:
            self.assertIsNone(leave.guide(q))

    def test_new_api_route_does_not_call_model_or_mock_annual(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                main.folders, 'DB_PATH', Path(directory) / 'folders.db'):
            main.folders.initialize()
            main.knowledge.initialize()
            with patch.object(main.assistant,'ask',side_effect=AssertionError('should not call legacy card')) as legacy, \
                 patch.object(main.llm,'get_provider',side_effect=AssertionError('should not call model')) as provider:
                r=main.api_ask({'query':'공가를 쓰려고 합니다'})
                self.assertEqual(r['mode'],'source_unavailable')
                self.assertEqual(r['knowledge']['evidence'],[])
                self.assertIsNone(r['model'])
                selected=main.api_ask({'query':'공가를 쓰려고 합니다','leave_type':'official'})
                self.assertEqual(selected['mode'],'leave_guide')
                self.assertEqual(selected['leave_guide']['selected'],'official')
                self.assertIsNone(selected['model']);self.assertIsNone(selected['plan'])
                legacy.assert_not_called();provider.assert_not_called()

    def test_saved_card_path_is_preserved(self):
        with patch.object(main.assistant,'ask',return_value={'existing_card':True}) as call:
            r=main.api_ask({'query':'연가', 'card_id':'card-leave'})
        self.assertTrue(r['existing_card']);call.assert_called_once()

    def test_sources_and_no_numeric_entitlement(self):
        g=leave.guide('시간외근무 연가 전환')['leave_guide']
        self.assertEqual(g['selected'],'conversion');self.assertIn('제11조제4항',g['basis'])
        self.assertEqual(g['checked_at'],'2026-10-19')
        self.assertTrue(all(s['url'].startswith('https://') for s in g['sources']))
        self.assertIn('확정하지',g['notice'])

if __name__=='__main__': unittest.main()
