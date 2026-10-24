import unittest
from app import travel_journey
import test_travel,test_travel_files,test_travel_package


class JourneyTest(unittest.TestCase):
    setUp=test_travel.TravelApiTest.setUp
    tearDown=test_travel.TravelApiTest.tearDown
    request=test_travel.TravelApiTest.request
    create=test_travel.TravelApiTest.create
    evidence=test_travel.TravelApiTest.evidence
    decide=test_travel.TravelApiTest.decide
    upload=test_travel_files.ReceiptTest.upload
    confirm=test_travel_files.ReceiptTest.confirm
    prepared=test_travel_package.PackageTest.prepared
    draft=test_travel_package.PackageTest.draft

    def journey(self,c):return self.request('GET',f"/cases/{c['id']}/journey")
    def steps(self,j):return {s['id']:s for s in j['steps']}

    def test_six_steps_and_read_only(self):
        c=self.create();j=self.journey(c);after=self.request('GET',f"/cases/{c['id']}")
        self.assertEqual(len(j['steps']),6);self.assertEqual(c['version'],after['version'])
        self.assertEqual(c['events'],after['events']);self.assertEqual(c['workflow_revision'],after['workflow_revision'])
        self.assertFalse(j['package_integrity_checked'])

    def test_unverified_org_does_not_inherit_calculator(self):
        j=self.journey(self.create());self.assertEqual(self.steps(j)['calculate']['status'],'blocked')
        self.assertEqual(j['recommended_step'],'evidence')

    def test_pending_evidence_directs_to_review(self):
        c=self.evidence(self.create(),test_travel_files.TEXT);j=self.journey(c)
        self.assertEqual(j['recommended_step'],'review');self.assertEqual(self.steps(j)['review']['status'],'attention')

    def test_valid_calculation_is_not_final_approval(self):
        c=self.prepared();j=self.journey(c);s=self.steps(j)
        self.assertEqual(s['calculate']['status'],'recorded');self.assertIn('최종 지급액 확정은 아닙니다',s['calculate']['reason'])
        self.assertEqual(j['recommended_step'],'draft');self.assertEqual(s['draft']['status'],'waiting')

    def test_current_draft_still_requires_integrity_and_human_review(self):
        c=self.prepared();self.draft(c);j=self.journey(c);s=self.steps(j)
        self.assertEqual(j['recommended_step'],'handoff');self.assertEqual(s['draft']['status'],'recorded')
        self.assertEqual(s['handoff']['status'],'waiting');self.assertIn('묶음 검사',s['handoff']['reason'])
        self.assertFalse(j['package_integrity_checked'])

    def test_edit_marks_calculation_and_old_draft_for_review(self):
        c=self.prepared();self.draft(c)
        c=self.decide(c,reason='원본과 다시 대조한 검토 사유')
        j=self.journey(c);s=self.steps(j)
        self.assertEqual(s['calculate']['label'],'재계산 필요');self.assertEqual(s['draft']['status'],'attention')
        self.assertFalse(any(d['is_current'] for d in j['drafts']))

    def test_open_task_blocks_handoff_and_changes_current_draft(self):
        c=self.prepared();self.draft(c)
        c=self.request('POST',f"/cases/{c['id']}/tasks",dict(version=c['version'],workflow_revision=c['workflow_revision'],title='소속 기관 검토조건 추가 확인',note='원본 담당자에게 추가 대조'),201)
        j=self.journey(c)
        self.assertEqual(self.steps(j)['handoff']['status'],'attention')
        self.assertTrue(any(i['code']=='OPEN_MANUAL_TASK' for i in j['checklist']))
        self.assertFalse(any(d['is_current'] for d in j['drafts']))

    def test_missing_case_is_not_rendered(self):
        self.request('GET','/cases/missing/journey',status=404)

if __name__=='__main__':unittest.main()
