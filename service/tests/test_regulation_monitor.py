"""합성 개정·통신 장애·재시작·기존 초안 보존. 실제 DB·공식 사이트에 쓰지 않는다."""
import copy,json,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from app import regulation_monitor as monitor,regulation_registry as registry,regulation_sources as sources
from app import travel_calculator as calculator,travel_api,travel_validity,travel_rates
import test_travel_calculation

class MonitorTest(unittest.TestCase):
    request=test_travel_calculation.LegalCalculationTest.request
    create=test_travel_calculation.LegalCalculationTest.create
    evidence=test_travel_calculation.LegalCalculationTest.evidence
    decide=test_travel_calculation.LegalCalculationTest.decide
    normal=test_travel_calculation.LegalCalculationTest.normal
    calc=test_travel_calculation.LegalCalculationTest.calc

    def setUp(self):
        self.mon_tmp=tempfile.TemporaryDirectory();root=Path(self.mon_tmp.name)
        self.patches=[patch.object(registry,'DB_PATH',root/'monitor.db'),patch.object(registry,'OBJECTS',root/'objects'),
            patch.object(travel_validity,'today',return_value='2026-10-22')]
        for p in self.patches:p.start()
        test_travel_calculation.LegalCalculationTest.setUp(self)
        self.client.app.include_router(monitor.router);registry.initialize()
        self.base=calculator.load_bundle()

    def tearDown(self):
        test_travel_calculation.LegalCalculationTest.tearDown(self)
        for p in reversed(self.patches):p.stop()
        self.mon_tmp.cleanup()

    def synthetic_change(self,key='national',effective=None):
        return dict(source_id=key,title='[합성시험] 기준 개정',change_kind='본문 변경',previous_version='시험 전',current_version='시험 후',
            old_sha=self.base['sources'][key]['sha256'],new_sha='1'*64,original_url=self.base['sources'][key]['url'],candidate_url=self.base['sources'][key]['url'],
            before_text='시험 금액 25,000',after_text='시험 금액 30,000',delta=[dict(op='replace',old='25,000',new='30,000')],comparison_complete=True,effective_date=effective)

    def run_check(self,changes=None,errors=None):
        with registry.db() as c:c.execute("UPDATE runs SET started_at=?",((registry.now()-timedelta(minutes=2)).isoformat(),))
        data=dict(records=[dict(source_id=k,sha256=s['sha256']) for k,s in self.base['sources'].items()],changes=changes or [],errors=errors or [],complete=not errors)
        with patch.object(sources,'compare',return_value=data):return monitor.run_due(force=True)

    def prepared_trip(self,org='national-general'):
        return self.normal(organization_id=org,start_date='2026-10-21',end_date='2026-10-22',text='10/21 08:00 코레일 100원\n10/21 20:00 합성호텔 120,000원')

    def amount(self,c):return self.calc(c,lodging_nights=[dict(night='2026-10-21',region='seoul')])

    def test_unchanged_renews_case_not_amount_or_saved_draft_and_survives_reload(self):
        c=self.amount(self.prepared_trip());self.assertIsNone(c['calculation']['result']['estimated_total'])
        draft=self.request('POST',f"/cases/{c['id']}/drafts",dict(version=c['version']),201)
        old_print=self.client.get(draft['json_url']+'/print').text
        result=self.run_check();self.assertEqual(result['status'],'unchanged');self.assertEqual(result['refreshed_cases'],[c['id']])
        self.assertEqual(calculator.load_bundle()['verified_through'],'2026-10-22')
        fresh=self.request('GET',f"/cases/{c['id']}")
        self.assertTrue(fresh['calculation']['stale']);self.assertTrue(fresh['calculation_inputs_reset'])
        self.assertEqual(fresh['version'],c['version']+1)
        self.assertEqual(old_print,self.client.get(draft['json_url']+'/print').text)
        self.assertEqual(self.amount(fresh)['calculation']['result']['estimated_total'],200100)
        registry.initialize() # restart schema init is idempotent
        self.assertEqual(calculator.load_bundle()['verified_through'],'2026-10-22')
        self.assertEqual(len(registry.runs()),1)
        with travel_api.db() as db:
            saved=db.execute('SELECT rulepack_snapshot FROM travel_calculations WHERE case_id=? ORDER BY case_version',(c['id'],)).fetchall()
            self.assertEqual([json.loads(x[0])['verified_through'] for x in saved],['2026-10-20','2026-10-22'])

    def test_change_blocks_and_marks_cached_amount_stale_and_review_never_approves(self):
        with patch.object(travel_validity,'today',return_value='2026-10-20'):c=self.amount(self.prepared_trip())
        self.assertEqual(c['calculation']['result']['estimated_total'],200100)
        draft=self.request('POST',f"/cases/{c['id']}/drafts",dict(version=c['version']),201)
        old_print=self.client.get(draft['json_url']+'/print').text
        self.run_check([self.synthetic_change()]);change=registry.change_rows()[0]
        detail=monitor.change_detail(change['id']);self.assertEqual(detail['affected'][0]['id'],c['id'])
        self.assertIn('25,000',detail['sources'][0]['before_text'])
        fresh=self.request('GET',f"/cases/{c['id']}");self.assertTrue(fresh['calculation']['stale'])
        latest=self.amount(fresh);blocked=latest['calculation']['result'];self.assertIsNone(blocked['estimated_total'])
        self.assertEqual(blocked['blockers'][0]['code'],'REGULATION_CHANGED')
        new_draft=self.request('POST',f"/cases/{c['id']}/drafts",dict(version=latest['version']),201)
        self.assertNotIn('200,100',self.client.get(new_draft['json_url']+'/print').text)
        self.assertEqual(old_print,self.client.get(draft['json_url']+'/print').text)
        response=self.client.post(f"/api/regulations/changes/{change['id']}/review",json=dict(revision=1,action='acknowledge',reason='합성 개정 검토 메모'))
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['state'],'reviewed')
        self.assertTrue(registry.holds(calculator.select_pack('national-general'),fresh['trip_json']))
        self.assertEqual(self.client.post(f"/api/regulations/changes/{change['id']}/review",json=dict(revision=1,action='defer',reason='충돌')).status_code,409)
        self.run_check() # upstream rollback alone must not erase a detected issue
        self.assertEqual(calculator.load_bundle()['verified_through'],'2026-10-20')

    def test_profile_and_effective_date_limit_potential_impacts(self):
        national=self.prepared_trip();province=self.prepared_trip('gg-province')
        self.run_check([self.synthetic_change('gyeonggi','2026-10-22')])
        issue=registry.change_rows()[0]
        self.assertEqual([a['id'] for a in monitor.affected(issue)],[province['id']])
        p=calculator.select_pack('gg-province')
        self.assertFalse(registry.holds(p,dict(end_date='2026-10-21')))
        self.assertTrue(registry.holds(p,dict(end_date='2026-10-22')))
        self.assertFalse(registry.holds(calculator.select_pack('national-general'),national['trip_json']))

    def test_partial_error_never_extends_and_detected_change_still_creates_issue(self):
        r=self.run_check(errors=['guide: timeout'])
        self.assertEqual(r['status'],'failed');self.assertEqual(calculator.load_bundle()['verified_through'],'2026-10-20')
        self.assertLess(datetime.fromisoformat(registry.settings()['next_check_at']),registry.now()+timedelta(hours=2))
        r=self.run_check([self.synthetic_change()],['guide: timeout'])
        self.assertEqual(r['status'],'changed');self.assertEqual(len(registry.change_rows()),1)

    def test_repeated_detection_is_one_issue_and_new_cases_appear(self):
        self.run_check([self.synthetic_change()]);self.run_check([self.synthetic_change()])
        self.assertEqual(len(registry.change_rows()),1)
        c=self.prepared_trip();self.assertEqual(monitor.change_detail(registry.change_rows()[0]['id'])['affected'][0]['id'],c['id'])

    def test_lease_due_disable_cooldown_and_recovery(self):
        first,claimed=registry.claim();self.assertTrue(claimed)
        second,claimed=registry.claim(True);self.assertFalse(claimed);self.assertEqual(first,second)
        with registry.db() as c:c.execute('UPDATE runs SET lease_until=?,started_at=?',((registry.now()-timedelta(seconds=1)).isoformat(),(registry.now()-timedelta(minutes=20)).isoformat()))
        second,claimed=registry.claim();self.assertTrue(claimed);self.assertNotEqual(first,second)
        registry.finish(second,monitor.base_bundle()[0],self.base,dict(status='failed',summary='합성 실패'))
        self.assertEqual(registry.claim()[0],None)
        self.assertFalse(registry.claim(True)[1]) # manual cooldown
        with registry.db() as c:c.execute('UPDATE settings SET enabled=0,next_check_at=?',(registry.stamp(),))
        self.assertEqual(registry.claim()[0],None)

    def test_settings_conflicts_and_public_controls_readonly(self):
        s=monitor.status();self.assertEqual(s['interval_hours'],24)
        body=dict(revision=s['revision'],enabled=False,interval_hours=12)
        self.assertEqual(self.client.patch('/api/regulations/settings',json=body).status_code,200)
        self.assertEqual(self.client.patch('/api/regulations/settings',json=body).status_code,409)
        with patch.object(monitor,'readonly',return_value=True):
            self.assertTrue(self.client.get('/api/regulations/status').json()['public_read_only'])
            self.assertEqual(self.client.post('/api/regulations/check',json={}).status_code,403)
            self.assertEqual(self.client.patch('/api/regulations/settings',json=body).status_code,403)

    def test_changed_static_bundle_ignores_old_certificate_and_other_rates_cannot_auto_publish(self):
        self.run_check();self.assertEqual(calculator.load_bundle()['verified_through'],'2026-10-22')
        replacement=copy.deepcopy(self.base);replacement['rates']['daily']=123
        path=Path(self.mon_tmp.name)/'new.json';path.write_text(registry.dumps(replacement),encoding='utf-8')
        with patch.object(calculator,'BUNDLE_PATH',path):self.assertEqual(calculator.load_bundle()['verified_through'],'2026-10-20')
        key,claimed=registry.claim(True)
        # Obtain a new lease after cooldown for the tamper guard.
        if not claimed:
            with registry.db() as c:c.execute('UPDATE runs SET started_at=?',((registry.now()-timedelta(minutes=2)).isoformat(),))
            key,claimed=registry.claim(True)
        with self.assertRaisesRegex(ValueError,'계산 기준'):
            registry.finish(key,monitor.base_bundle()[0],self.base,dict(status='unchanged'),replacement)

    def source_fixture(self,url):
        if url.startswith('https://www.law.go.kr/LSW/lsInfoR.do?lsiSeq=290313&lsId=009402'):
            return (registry.ROOT/'reference_data/travel-monitor-20261023/national-full.html').read_bytes()
        for key,digest in (('travel_annex1','169708637'),('travel_annex2','169708643')):
            if url=='https://www.law.go.kr/LSW/flDownload.do?flSeq='+digest:return travel_rates.source_path(self.base['sources'][key]).read_bytes()
        for key,(canonical,param) in sources.CURRENT.items():
            if url==canonical:return (sources.registry.ROOT/'reference_data/travel-recheck-20261020'/(key+'_current.html')).read_bytes()
        if 'mode=view&cntId=695' in url:
            return ('''<a href="javascript:Jnit_boardDownload('/board/file/bbs_0000000000000035/695/FILE_000000100073530/7aa6b30cca5926d04','x','2');">공무원보수 등의 업무지침(인사혁신처예규 제226호).pdf</a>''').encode()
        for s in self.base['sources'].values():
            if url==s.get('review_url',s['url']):return travel_rates.source_path(s).read_bytes()
        raise ValueError('unregistered URL '+str(url))

    def test_real_registered_fixtures_match_without_network(self):
        with patch.object(sources,'fetch',side_effect=self.source_fixture):r=sources.compare(self.base)
        self.assertTrue(r['complete'],r['errors']);self.assertEqual(r['changes'],[]);self.assertEqual(len(r['records']),16)

    def test_current_annex_pointer_is_followed_and_failure_never_certifies(self):
        def changed(url):
            raw=self.source_fixture(url)
            if url.startswith('https://www.law.go.kr/LSW/lsInfoR.do?lsiSeq=290313&lsId=009402'):
                return raw.replace(b'169708643',b'999999999')
            return raw
        with patch.object(sources,'fetch',side_effect=changed):r=sources.compare(self.base)
        self.assertFalse(r['complete']);self.assertTrue(any('travel_annex2' in e for e in r['errors']))
        def wrong_identity(url):
            raw=self.source_fixture(url)
            if url.startswith('https://www.law.go.kr/LSW/lsInfoR.do?lsiSeq=290313&lsId=009402'):
                return raw.replace(b'id="lsiSeq" name="lsiSeq" value="290313"',b'id="lsiSeq" name="lsiSeq" value="999999"')
            return raw
        with patch.object(sources,'fetch',side_effect=wrong_identity):r=sources.compare(self.base)
        self.assertFalse(r['complete']);self.assertTrue(any('national_attachments' in e for e in r['errors']))

    def test_same_day_recheck_refreshes_evidence_not_rates_or_version(self):
        first=monitor.renewed(self.base,'2026-10-22','first','a'*64)
        second=monitor.renewed(first,'2026-10-22','second','b'*64)
        self.assertEqual(first['version'],second['version'])
        self.assertEqual(registry.signature(first),registry.signature(second))
        self.assertEqual(second['verification_certificate']['run_id'],'second')

    def october23_fixture(self,url):
        if url==self.base['sources']['national']['review_url']:
            return (registry.ROOT/'reference_data/travel-monitor-20261023/linked-after.html').read_bytes()
        return self.source_fixture(url)

    def test_october23_other_law_header_is_not_a_travel_regulation_change(self):
        with patch.object(sources,'fetch',side_effect=self.october23_fixture):r=sources.compare(self.base)
        self.assertTrue(r['complete'],r['errors'])
        self.assertEqual(r['changes'],[])

    def test_national_body_and_attachment_edits_are_still_changes(self):
        for before,after in [('일비는','일비는 합성 변경'),('id="Y001600"','id="Y001600"')]:
            raw=self.october23_fixture(self.base['sources']['national']['review_url'])
            if before=='일비는':
                self.assertIn(before.encode(),raw)
                changed=raw.replace(before.encode(),after.encode(),1)
            else:
                changed=raw.replace(b'<h2 id="009402">',b'<h2 id="009402"><img src="/LSW/flDownload.do?flSeq=999999999">',1)
            def fetch(url):
                return changed if url==self.base['sources']['national']['review_url'] else self.source_fixture(url)
            with patch.object(sources,'fetch',side_effect=fetch):r=sources.compare(self.base)
            self.assertTrue(r['complete'],r['errors']);self.assertEqual([s['source_id'] for s in r['changes']],['national'])
            self.assertTrue(r['changes'][0]['comparison_complete'])

    def test_national_identity_and_layout_fail_closed(self):
        raw=self.october23_fixture(self.base['sources']['national']['review_url'])
        for changed in (raw.replace(b'<h2 id="009402">',b'<h2 id="009499">'),
                        raw.replace(b'lsiSeq=290313',b'lsiSeq=999999'),
                        raw.replace(b'<h2 id="009402">',b'<h2 id="009402">ambiguous</h2><h2 id="009402">')):
            def fetch(url):
                return changed if url==self.base['sources']['national']['review_url'] else self.source_fixture(url)
            with patch.object(sources,'fetch',side_effect=fetch):r=sources.compare(self.base)
            self.assertFalse(r['complete']);self.assertTrue(any(e.startswith('national:') for e in r['errors']))

    def recorded_october23_change(self):
        root=registry.ROOT/'reference_data/travel-monitor-20261023'
        old=registry.store_object((root/'linked-before.html').read_bytes())
        new=registry.store_object((root/'linked-after.html').read_bytes())
        change=self.synthetic_change();change.update(old_sha=old,new_sha=new,previous_version=self.base['sources']['national']['version'],
            current_version=self.base['sources']['national']['version'],comparison_complete=False)
        self.run_check([change])
        return registry.change_rows()[0]

    def test_verified_cross_law_false_positive_releases_only_its_hold_with_audit(self):
        trip=self.prepared_trip();issue=self.recorded_october23_change()
        self.assertTrue(registry.holds(calculator.select_pack('national-general'),trip['trip_json']))
        with registry.db() as c:c.execute('UPDATE runs SET started_at=?',((registry.now()-timedelta(minutes=2)).isoformat(),))
        with patch.object(sources,'fetch',side_effect=self.october23_fixture):result=monitor.run_due(force=True)
        self.assertEqual(result['status'],'unchanged');self.assertEqual(result['resolved_nonmaterial'],[issue['id']])
        self.assertEqual(calculator.load_bundle()['verified_through'],'2026-10-22')
        detail=monitor.change_detail(issue['id'])
        self.assertTrue(detail['resolution_verified']);self.assertEqual(detail['affected'],[])
        self.assertEqual(detail['history'][-1]['action'],'nonmaterial_verified')
        self.assertEqual(detail['sources'][0]['new_sha'],issue['sources'][0]['new_sha'])
        self.assertFalse(registry.holds(calculator.select_pack('national-general'),trip['trip_json']))
        registry.initialize()
        self.assertTrue(monitor.change_detail(issue['id'])['resolution_verified'])
        result=self.client.post(f"/api/regulations/changes/{issue['id']}/review",json=dict(revision=detail['revision'],action='reopen',reason='증거 재검토'))
        self.assertEqual(result.status_code,200)
        self.assertTrue(registry.holds(calculator.select_pack('national-general'),trip['trip_json']))

    def test_failed_full_check_or_corrupt_archive_cannot_resolve_false_positive(self):
        issue=self.recorded_october23_change()
        def fail(url):
            if url=='https://www.law.go.kr/LSW/flDownload.do?flSeq=169708643':raise ValueError('합성 통신 실패')
            return self.october23_fixture(url)
        with registry.db() as c:c.execute('UPDATE runs SET started_at=?',((registry.now()-timedelta(minutes=2)).isoformat(),))
        with patch.object(sources,'fetch',side_effect=fail):result=monitor.run_due(force=True)
        self.assertEqual(result['status'],'failed');self.assertNotIn('resolution',monitor.change_detail(issue['id']))
        (registry.OBJECTS/issue['sources'][0]['new_sha']).write_bytes(b'corrupted')
        with registry.db() as c:c.execute('UPDATE runs SET started_at=?',((registry.now()-timedelta(minutes=2)).isoformat(),))
        with patch.object(sources,'fetch',side_effect=self.source_fixture):result=monitor.run_due(force=True)
        self.assertEqual(result['status'],'changed');self.assertNotIn('resolution',monitor.change_detail(issue['id']))
        self.assertEqual(calculator.load_bundle()['verified_through'],'2026-10-20')

    def test_false_positive_does_not_clear_a_separate_real_change_or_missing_proof(self):
        issue=self.recorded_october23_change()
        self.run_check([self.synthetic_change('gyeonggi')])
        with registry.db() as c:c.execute('UPDATE runs SET started_at=?',((registry.now()-timedelta(minutes=2)).isoformat(),))
        with patch.object(sources,'fetch',side_effect=self.october23_fixture):result=monitor.run_due(force=True)
        self.assertEqual(result['resolved_nonmaterial'],[issue['id']]);self.assertEqual(result['status'],'changed')
        self.assertEqual(calculator.load_bundle()['verified_through'],'2026-10-20')
        trip=dict(end_date='2026-10-22')
        self.assertFalse(registry.holds(calculator.select_pack('national-general'),trip))
        self.assertTrue(registry.holds(calculator.select_pack('gg-province'),trip))
        (registry.OBJECTS/issue['sources'][0]['new_sha']).unlink()
        self.assertFalse(monitor.change_detail(issue['id'])['resolution_verified'])
        self.assertTrue(registry.holds(calculator.select_pack('national-general'),trip))

    def test_html_table_and_link_and_current_version_change_detection(self):
        def changed(url):
            raw=self.source_fixture(url)
            if url==self.base['sources']['gyeonggi']['review_url']:raw=raw.replace('</body>'.encode(),'<table><tr><td>금액 99999</td></tr></table></body>'.encode())
            return raw
        with patch.object(sources,'fetch',side_effect=changed):r=sources.compare(self.base)
        self.assertEqual([x['source_id'] for x in r['changes']],['gyeonggi'])
        self.assertIn('99999',r['changes'][0]['after_text'])
        def new_version(url):
            if url==sources.CURRENT['national_training'][0]:return self.source_fixture(url).replace(b'2100000286938',b'2100000999999')
            return self.source_fixture(url)
        with patch.object(sources,'fetch',side_effect=new_version):r=sources.compare(self.base)
        change=next(x for x in r['changes'] if x['source_id']=='national_training')
        self.assertFalse(change['comparison_complete']);self.assertIn('999999',change['current_version'])

    def test_pdf_change_and_malformed_download_never_count_as_unchanged(self):
        def pdf_changed(url):
            raw=self.source_fixture(url)
            if url=='https://www.law.go.kr/LSW/flDownload.do?flSeq=169708643':raw=raw.replace(b'%%EOF',b'% synthetic-change\n%%EOF')
            return raw
        with patch.object(sources,'fetch',side_effect=pdf_changed):r=sources.compare(self.base)
        self.assertEqual([x['source_id'] for x in r['changes']],['travel_annex2'])
        def bad(url):
            if url==self.base['sources']['guide']['review_url']:return b'<html>error</html>'
            return self.source_fixture(url)
        with patch.object(sources,'fetch',side_effect=bad):r=sources.compare(self.base)
        self.assertFalse(r['complete']);self.assertTrue(r['errors'])

    def test_source_url_redirect_guard(self):
        for url in ['http://law.go.kr/x','https://example.org/','https://www.law.go.kr:8443/x','https://u:p@law.go.kr/x']:
            with self.assertRaises(ValueError):sources.safe_url(url)
        with self.assertRaises(ValueError):sources.Redirect().redirect_request(None,None,302,'',{},'http://127.0.0.1:8766/api/config')

    def test_embedded_table_image_identifier_changes_are_material(self):
        raw=travel_rates.source_path(self.base['sources']['national_training']).read_bytes()
        self.assertIn(b'flSeq=170628099',raw)
        self.assertNotEqual(sources.material(raw),sources.material(raw.replace(b'flSeq=170628099',b'flSeq=999999999')))

    def test_latest_list_attachment_version_conflict_fails_closed(self):
        def mismatch(url):
            raw=self.source_fixture(url)
            if 'mode=view&cntId=695' in url:return raw.replace('제226호'.encode(),'제999호'.encode())
            return raw
        with patch.object(sources,'fetch',side_effect=mismatch):r=sources.compare(self.base)
        self.assertFalse(r['complete']);self.assertTrue(any('버전' in e for e in r['errors']))

    def test_archived_evidence_corruption_cannot_be_reused(self):
        digest=registry.store_object(b'original evidence')
        (registry.OBJECTS/digest).write_bytes(b'changed evidence')
        with self.assertRaisesRegex(ValueError,'해시'):registry.store_object(b'original evidence')

if __name__=='__main__':unittest.main()
