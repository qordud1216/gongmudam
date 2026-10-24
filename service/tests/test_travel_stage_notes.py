import unittest
from app import travel_api
import test_travel_journey


class StageNotesTest(unittest.TestCase):
    setUp=test_travel_journey.JourneyTest.setUp
    tearDown=test_travel_journey.JourneyTest.tearDown
    request=test_travel_journey.JourneyTest.request
    create=test_travel_journey.JourneyTest.create
    evidence=test_travel_journey.JourneyTest.evidence
    decide=test_travel_journey.JourneyTest.decide
    upload=test_travel_journey.JourneyTest.upload
    confirm=test_travel_journey.JourneyTest.confirm
    prepared=test_travel_journey.JourneyTest.prepared
    draft=test_travel_journey.JourneyTest.draft

    def save(self,c,**changes):
        body=dict(version=c['version'],stage='calculate',title='개별 확인사항',body='담당자에게 원본을 다시 확인할 사항')
        body.update(changes)
        return self.request('POST',f"/cases/{c['id']}/stage-notes",body,201)

    def notes(self,c):return self.request('GET',f"/cases/{c['id']}/stage-notes")

    def test_persistent_case_stage_context(self):
        c=self.create();result=self.save(c)
        self.save(c,stage='evidence',title='증빙 단계 기록')
        travel_api.initialize()
        notes=self.notes(c)['notes']
        self.assertEqual(len(notes),2)
        self.assertEqual({n['stage'] for n in notes},{'calculate','evidence'})
        self.assertEqual(self.notes(self.create())['notes'],[])
        self.assertFalse(result['notes'][0]['context_changed'])
        self.assertEqual(result['notes'][0]['verification'],'user_unverified')

    def test_invalid_inputs_and_missing_case(self):
        c=self.create();body=dict(version=1,stage='trip',title='정상 제목',body='정상 기록 본문입니다')
        for changes in [dict(stage='law'),dict(title='  '),dict(body='  '),dict(body='x'*2001),dict(verified=True)]:
            self.request('POST',f"/cases/{c['id']}/stage-notes",body|changes,422)
        self.request('GET','/cases/missing/stage-notes',status=404)
        self.request('POST','/cases/missing/stage-notes',body,404)

    def test_stale_write_rejected_and_saved_note_recheck(self):
        c=self.create();self.save(c)
        updated=self.evidence(c,'10/15 코레일 52,300원 승인')
        self.request('POST',f"/cases/{c['id']}/stage-notes",dict(version=c['version'],stage='trip',title='이전 화면',body='변경 전 화면에서 작성한 기록'),409)
        self.assertTrue(self.notes(updated)['notes'][0]['context_changed'])
        self.assertFalse(self.save(updated)['notes'][0]['context_changed'])

    def test_note_does_not_change_calculation_draft_or_package(self):
        c=self.prepared();draft=self.draft(c)
        before=self.request('GET',f"/cases/{c['id']}")
        package=self.client.get(draft['package_url']).content
        marker='NOTE_ONLY_PRIVATE_781462'
        self.save(c,body=marker)
        after=self.request('GET',f"/cases/{c['id']}")
        self.assertEqual(before,after)
        journey=self.request('GET',f"/cases/{c['id']}/journey")
        self.assertTrue(journey['drafts'][0]['is_current'])
        self.assertEqual(package,self.client.get(draft['package_url']).content)
        fresh=self.draft(c)
        import io,zipfile
        with zipfile.ZipFile(io.BytesIO(self.client.get(fresh['package_url']).content)) as z:
            self.assertFalse(any(marker.encode() in z.read(name) for name in z.namelist()))

    def test_get_is_read_only_and_content_is_retained_as_text(self):
        c=self.create();text='<script>alert("x")</script>'
        self.save(c,body=text)
        before=self.request('GET',f"/cases/{c['id']}")
        self.assertEqual(self.notes(c)['notes'][0]['body'],text)
        self.assertEqual(before,self.request('GET',f"/cases/{c['id']}"))


if __name__=='__main__':unittest.main()
