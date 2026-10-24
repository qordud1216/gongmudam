"""출장 수정의 사전 비교·원자성·자료 고정 및 재검토 경계."""
import unittest
from unittest.mock import patch
from tests import test_travel_organizations as organizations
from app import travel_api


class TripEditTest(unittest.TestCase):
    setUp=organizations.OrganizationTest.setUp
    tearDown=organizations.OrganizationTest.tearDown
    request=organizations.OrganizationTest.request
    create=organizations.OrganizationTest.create
    org=organizations.OrganizationTest.org
    rule=organizations.OrganizationTest.rule
    evidence=organizations.OrganizationTest.evidence
    decide=organizations.OrganizationTest.decide

    def body(self,c,**changes):
        return {**c['trip_json'],'version':c['version'],'reason':'실제 출장 목적과 기간을 정정함','purpose':'실제 회의 참석',**changes}

    def preview(self,c,**changes):
        body=self.body(c,**changes)
        return body,self.request('POST',f"/cases/{c['id']}/change-preview",body)

    def apply(self,c,body,preview,status=200):
        return self.request('PATCH',f"/cases/{c['id']}/trip",{**body,'preview_digest':preview['preview_digest'],'confirmed':True},status)

    def test_preview_is_read_only_and_confirmed_change_is_audited(self):
        c=self.create();body,p=self.preview(c)
        self.assertEqual(self.request('GET',f"/cases/{c['id']}"),c)
        updated=self.apply(c,body,p)
        self.assertEqual(updated['version'],2)
        self.assertEqual(updated['trip_json']['purpose'],body['purpose'])
        audit=updated['events'][0]
        self.assertEqual(audit['event_type'],'TRIP_CHANGED')
        self.assertEqual(audit['payload']['before']['trip'],c['trip_json'])
        self.assertEqual(audit['payload']['after']['trip'],updated['trip_json'])

    def test_included_transactions_reset_but_exclusions_and_dates_remain(self):
        c=self.evidence(self.create(),'10/15 08:00 코레일 52,300원 승인\n10/17 18:00 코레일 52,300원 승인')
        c=self.decide(c,index=0);c=self.decide(c,index=1,decision='exclude')
        body,p=self.preview(c,start_date='2026-10-16')
        self.assertEqual(len(p['reset_transactions']),1)
        updated=self.apply(c,body,p)
        rows=updated['review']['transactions']
        self.assertEqual(rows[0]['decision'],'pending');self.assertEqual(rows[1]['decision'],'exclude')
        self.assertEqual(rows[0]['transaction_date'],'2026-10-15')
        self.assertTrue(rows[0]['flags']);self.assertEqual(updated['review']['candidate_total'],0)
        self.assertIn('출장정보 변경',rows[0]['reason'])

    def test_saved_draft_and_package_do_not_change(self):
        c=self.decide(self.evidence(self.create(),'10/15 08:00 코레일 52,300원 승인'))
        d=self.request('POST',f"/cases/{c['id']}/drafts",{'version':c['version']},201)
        original=self.client.get(d['json_url']).content;zip_before=self.client.get(d['package_url']).content
        body,p=self.preview(c);self.apply(c,body,p)
        self.assertEqual(self.client.get(d['json_url']).content,original)
        self.assertEqual(self.client.get(d['package_url']).content,zip_before)

    def test_calculation_is_stale_and_inputs_require_reconfirmation(self):
        c=self.request('POST','/demo-scenarios/ordinary/prepare',{'new_copy':True})
        self.assertFalse(c['calculation']['stale'])
        body,p=self.preview(c)
        updated=self.apply(c,body,p)
        self.assertTrue(updated['calculation']['stale']);self.assertTrue(updated['calculation_inputs_reset'])
        self.assertEqual(updated['calculation']['id'],c['calculation']['id'])
        self.assertEqual(updated['documents'],c['documents'])
        self.assertEqual(updated['data_origin'],'synthetic_demo')
        reloaded=self.request('GET',f"/cases/{c['id']}")
        self.assertTrue(reloaded['calculation_inputs_reset'])

    def test_official_bundle_is_never_reselected(self):
        c=self.create(organization_id='national-general')
        with travel_api.db() as db:
            before=db.execute('SELECT snapshot FROM travel_case_legalpacks WHERE case_id=?',(c['id'],)).fetchone()['snapshot']
        with patch.object(travel_api.calculator,'select_pack',return_value=None):
            body,p=self.preview(c);updated=self.apply(c,body,p)
        self.assertIsNotNone(updated['legal_profile'])
        with travel_api.db() as db:
            self.assertEqual(db.execute('SELECT snapshot FROM travel_case_legalpacks WHERE case_id=?',(c['id'],)).fetchone()['snapshot'],before)

    def test_organization_cannot_be_switched(self):
        c=self.create()
        self.request('POST',f"/cases/{c['id']}/change-preview",self.body(c,organization_id='national-general'),422)

    def test_preview_digest_blocks_unseen_changes(self):
        c=self.create();body,p=self.preview(c)
        self.apply(c,{**body,'destination':'서울'},p,409)
        self.assertEqual(self.request('GET',f"/cases/{c['id']}")['version'],1)

    def test_concurrent_case_update_rejected(self):
        c=self.create();body,p=self.preview(c)
        self.evidence(c,'10/15 08:00 코레일 52,300원 승인')
        self.apply(c,body,p,409)

    def test_current_registered_rules_settings_and_forms_are_refreshed(self):
        o=self.org(required_forms=['기관 정산서']);c=self.create(organization_id=o['id']);self.rule(o)
        self.request('PATCH',f"/organizations/{o['id']}/settings",dict(revision=1,required_forms=['새 정산서'],note='서식 변경'))
        body,p=self.preview(c);updated=self.apply(c,body,p)
        self.assertEqual(updated['profile_snapshot']['settings_revision'],2)
        self.assertEqual(updated['profile_snapshot']['form_bindings'][0]['name'],'새 정산서')
        self.assertEqual(len(updated['rule_snapshot']),1)
        self.assertIsNone(updated['legal_profile'])

    def test_registry_update_after_preview_rejected(self):
        o=self.org();c=self.create(organization_id=o['id']);body,p=self.preview(c)
        self.rule(o)
        self.apply(c,body,p,409)
        self.assertEqual(self.request('GET',f"/cases/{c['id']}")['rule_snapshot'],[])

    def test_confirmation_and_input_validation(self):
        c=self.create();body,p=self.preview(c)
        self.request('PATCH',f"/cases/{c['id']}/trip",body,422)
        self.request('POST',f"/cases/{c['id']}/change-preview",self.body(c,end_date='2026-10-14'),422)
        self.request('POST',f"/cases/{c['id']}/change-preview",self.body(c,reason=' '),422)

    def test_noop_and_refresh_only(self):
        o=self.org();c=self.create(organization_id=o['id'])
        self.request('POST',f"/cases/{c['id']}/change-preview",self.body(c,purpose=c['trip_json']['purpose']),422)
        self.rule(o)
        body,p=self.preview(c,purpose=c['trip_json']['purpose'])
        self.assertEqual(p['changed_fields'],[])
        self.assertEqual(len(self.apply(c,body,p)['rule_snapshot']),1)
