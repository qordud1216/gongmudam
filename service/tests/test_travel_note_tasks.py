import io
import unittest
import zipfile
import test_travel_stage_notes as notes


class NoteTaskTest(unittest.TestCase):
    setUp=notes.StageNotesTest.setUp
    tearDown=notes.StageNotesTest.tearDown
    request=notes.StageNotesTest.request
    create=notes.StageNotesTest.create
    evidence=notes.StageNotesTest.evidence
    decide=notes.StageNotesTest.decide
    upload=notes.StageNotesTest.upload
    confirm=notes.StageNotesTest.confirm
    prepared=notes.StageNotesTest.prepared
    draft=notes.StageNotesTest.draft
    save=notes.StageNotesTest.save
    notes=notes.StageNotesTest.notes

    def connect(self,c,n,status=201,**changes):
        body=dict(version=c['version'],workflow_revision=c['workflow_revision'],title='원본 제공조건 확인',note='제출 가능한 보완 메모',export_confirmed=True)
        body.update(changes)
        return self.request('POST',f"/cases/{c['id']}/stage-notes/{n['id']}/task",body,status)

    def test_connection_workflow_only_and_duplicate_retry(self):
        c=self.prepared();d=self.draft(c);n=self.save(c)['notes'][0]
        old=self.client.get(d['package_url']).content
        updated=self.connect(c,n)
        self.assertEqual(updated['version'],c['version'])
        self.assertEqual(updated['workflow_revision'],c['workflow_revision']+1)
        self.assertEqual(updated['calculation'],c['calculation'])
        self.assertEqual(len(updated['tasks']),1)
        self.assertEqual(self.connect(c,n),updated)
        self.assertEqual(old,self.client.get(d['package_url']).content)
        j=self.request('GET',f"/cases/{c['id']}/journey")
        self.assertFalse(j['drafts'][0]['is_current'])
        self.assertEqual(next(s for s in j['steps'] if s['id']=='handoff')['status'],'attention')

    def test_export_requires_explicit_acknowledgement(self):
        c=self.create();n=self.save(c)['notes'][0]
        self.connect(c,n,422,export_confirmed=False)
        self.assertIsNone(self.notes(c)['notes'][0]['task'])
        self.assertEqual(self.request('GET',f"/cases/{c['id']}")['workflow_revision'],0)

    def test_changed_context_requires_recheck_and_current_version(self):
        c=self.create();n=self.save(c)['notes'][0]
        newer=self.evidence(c,'10/15 코레일 52,300원 승인')
        self.connect(newer,n,422)
        self.connect(c,n,409,context_confirmed=True)
        newer=self.connect(newer,n,context_confirmed=True)
        self.assertTrue(self.notes(newer)['notes'][0]['context_changed'])
        self.assertEqual(self.notes(newer)['notes'][0]['verification'],'user_unverified')

    def test_stale_workflow_does_not_create_orphan_task(self):
        c=self.create();n=self.save(c)['notes'][0]
        self.request('POST',f"/cases/{c['id']}/tasks",dict(version=c['version'],workflow_revision=0,title='다른 보완 작업'),201)
        self.connect(c,n,409)
        self.assertIsNone(self.notes(c)['notes'][0]['task'])
        self.assertEqual(len(self.request('GET',f"/cases/{c['id']}")['tasks']),1)

    def test_case_isolation_and_missing_note(self):
        c=self.create();n=self.save(c)['notes'][0]
        self.connect(self.create(),n,404)
        self.connect(c,{'id':'missing'},404)

    def test_connected_status_tracks_done_and_reopen(self):
        c=self.create();n=self.save(c)['notes'][0];c=self.connect(c,n)
        task=self.notes(c)['notes'][0]['task'];self.assertEqual(task['status'],'open')
        for action,status in [('done','done'),('reopen','open')]:
            c=self.request('PATCH',f"/cases/{c['id']}/tasks/{task['id']}",dict(version=c['version'],workflow_revision=c['workflow_revision'],action=action,reason='담당자와 확인한 처리 사유'))
            link=self.notes(c)['notes'][0]['task']
            self.assertEqual(link['status'],status)
            self.assertEqual(link['resolution'],'담당자와 확인한 처리 사유')
            self.assertEqual(len(c['tasks']),1)

    def test_new_package_contains_selected_task_text_only(self):
        c=self.prepared();private='PRIVATE_NOTE_BODY_829153'
        n=self.save(c,body=private)['notes'][0]
        c=self.connect(c,n,note='EXPORT_TASK_NOTE_918274')
        d=self.draft(c)
        with zipfile.ZipFile(io.BytesIO(self.client.get(d['package_url']).content)) as z:
            data=b'\n'.join(z.read(name) for name in z.namelist())
            self.assertNotIn(private.encode(),data)
            self.assertIn(b'EXPORT_TASK_NOTE_918274',data)


if __name__=='__main__':unittest.main()
