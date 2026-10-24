"""출장정산 회귀시험. 각 시험은 독립 임시 DB만 사용한다."""
import csv
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import travel_api
from app.travel_engine import extract_situation, parse_evidence


class ParserTest(unittest.TestCase):
    def parse(self, text, start=date(2026,10,15), end=date(2026,10,17)):
        return parse_evidence(text, start, end, "card_sms")

    def test_standard_sms(self):
        rows, issues = self.parse("[카드]\n10/15 08:14 코레일 52,300원 승인")
        self.assertEqual(issues, [])
        self.assertEqual((rows[0]["amount"], rows[0]["category"], rows[0]["transaction_date"]), (52300,"transport","2026-10-15"))

    def test_invalid_dates_amounts_times_are_not_silent(self):
        for line in ["02/30 12:00 호텔 100원", "10/15 99:99 호텔 100원", "10/15 호텔 -100원", "10/15 호텔 10.50원", "10/15 호텔 1,23,000원", "10/15 호텔 0원", "금액 알 수 없음"]:
            with self.subTest(line=line):
                rows, issues = self.parse(line)
                self.assertEqual(rows, [])
                self.assertEqual(len(issues), 1)

    def test_multiple_amounts_rejected(self):
        rows, issues = self.parse("10/15 코레일 52,300원 승인 누계 70,000원")
        self.assertEqual(rows, [])
        self.assertTrue(issues)

    def test_year_boundary(self):
        rows, issues = self.parse("12/31 코레일 100원\n01/02 호텔 200원", date(2026,12,31),date(2027,1,2))
        self.assertEqual(issues, [])
        self.assertEqual([r["transaction_date"] for r in rows],["2026-12-31","2027-01-02"])

    def test_cancellation(self):
        rows, _ = self.parse("10/15 09:00 SRT 45,000원 승인취소")
        self.assertTrue(rows[0]["cancelled"])

    def test_no_invented_dates(self):
        result = extract_situation("부산으로 2박 3일 교육출장 다녀왔어")
        self.assertEqual(result["fields"]["destination"],"부산")
        self.assertEqual(result["fields"]["start_date"],"")
        self.assertIn("end_date",result["missing_fields"])

    def test_unknown_intent(self):
        self.assertEqual(extract_situation("물품 구매 도와줘")["intent"],"unknown")


class TravelApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Automatic certificates are installation state, never inputs to fixed legal examples.
        from app import regulation_registry
        self.monitor_override=patch.object(regulation_registry,'DB_PATH',Path(self.tmp.name)/'monitor.db')
        self.monitor_override.start()
        self.override = patch.object(travel_api, "DB_PATH", Path(self.tmp.name) / "travel.db")
        self.override.start()
        travel_api.initialize()
        app = FastAPI()
        app.include_router(travel_api.router)
        self.client = TestClient(app)
        self.trip = dict(organization_id="demo-city",work_pattern="일반근무",destination="부산",purpose="교육",start_date="2026-10-15",end_date="2026-10-17",transport="철도",overnight=True,meals_provided=False)

    def tearDown(self):
        self.client.close()
        self.override.stop()
        self.monitor_override.stop()
        self.tmp.cleanup()

    def request(self, method, path, body=None, status=200):
        response = self.client.request(method,"/api/travel"+path,json=body)
        self.assertEqual(response.status_code,status,response.text)
        return response.json()

    def create(self, **changes):
        return self.request("POST","/cases",{**self.trip,**changes},201)

    def evidence(self, case, text):
        return self.request("POST",f"/cases/{case['id']}/evidence",dict(version=case["version"],text=text,source_type="card_sms"))

    def decide(self, case, index=0, decision="include", reason="출장내역과 대조함", status=200):
        row = case["review"]["transactions"][index]
        return self.request("PATCH",f"/cases/{case['id']}/transactions/{row['id']}",dict(version=case["version"],decision=decision,reason=reason,category=row["category"]),status)

    def test_profile_and_scope(self):
        city = self.create()
        national = self.create(organization_id="demo-national")
        self.assertIn("CITY",city["profile_snapshot"]["rule_packs"])
        self.assertNotIn("CITY",[r["pack_id"] for r in national["rule_snapshot"]])
        self.assertEqual(len(self.request("GET","/bootstrap")["organizations"]),6)

    def test_validation(self):
        self.create()
        for changes in [dict(end_date="2026-10-01"),dict(start_date="invalid"),dict(organization_id="unknown"),dict(start_date="2026-10-17",overnight=True),dict(extra="bad")]:
            self.request("POST","/cases",{**self.trip,**changes},422)

    def test_no_auto_inclusion_or_official_verification(self):
        c = self.evidence(self.create(),"10/15 08:14 코레일 52,300원 승인")
        self.assertEqual(c["review"]["candidate_total"],0)
        self.assertIsNone(c["review"]["payable_amount"])
        self.assertFalse(c["review"]["transactions"][0]["official_verification"])
        c = self.decide(c)
        self.assertEqual(c["review"]["candidate_total"],52300)
        self.assertEqual(c["events"][0]["event_type"],"TRANSACTION_REVIEWED")

    def test_duplicate_idempotency(self):
        c = self.evidence(self.create(),"10/15 08:14 코레일 52,300원 승인\n10/15 08:14 코레일 52,300원 승인")
        self.assertEqual(c["import_result"],{"inserted":1,"duplicates_skipped":1})
        c = self.evidence(c,"10/15 08:14 코레일 52,300원 승인")
        self.assertEqual(len(c["review"]["transactions"]),1)
        self.assertEqual(c["import_result"]["duplicates_skipped"],1)

    def test_similar_transactions_flagged(self):
        c = self.evidence(self.create(),"10/15 08:14 코레일 52,300원\n10/15 08:15 코레일 52,300원")
        self.assertTrue(all(any("중복" in f for f in r["flags"]) for r in c["review"]["transactions"]))

    def test_cancellation_blocks_original_and_cancel(self):
        c = self.evidence(self.create(),"10/15 08:14 코레일 52,300원 승인\n10/16 08:14 코레일 52,300원 취소")
        self.decide(c,index=0,status=422)
        self.decide(c,index=1,status=422)
        self.assertEqual(c["review"]["candidate_total"],0)

    def test_late_cancellation_removes_previous_candidate(self):
        c = self.decide(self.evidence(self.create(),"10/15 08:14 코레일 52,300원"))
        self.assertEqual(c["review"]["candidate_total"],52300)
        c = self.evidence(c,"10/16 08:14 코레일 52,300원 취소")
        self.assertEqual(c["review"]["candidate_total"],0)

    def test_outside_period_and_missing_lodging(self):
        c = self.evidence(self.create(),"10/18 10:00 가람카페 6,500원")
        self.assertIn("출장기간 외 거래",c["review"]["transactions"][0]["flags"])
        self.assertTrue(any(f["code"]=="LODGING" for f in c["review"]["findings"]))

    def test_version_conflict_rolls_back(self):
        original = self.create()
        updated = self.evidence(original,"10/15 코레일 100원")
        self.request("POST",f"/cases/{original['id']}/evidence",dict(version=1,text="10/16 호텔 200원"),409)
        current = self.request("GET",f"/cases/{original['id']}")
        self.assertEqual(current["version"],updated["version"])
        self.assertEqual(len(current["review"]["transactions"]),1)

    def test_parse_failures_preserved_until_explicit_resolution(self):
        c = self.evidence(self.create(),"해석할 수 없는 결제내역")
        c = self.evidence(c,"10/15 코레일 100원")
        self.assertTrue(c["parse_issues"])
        c = self.request("POST",f"/cases/{c['id']}/resolve-issues",dict(version=c["version"],reason="위 거래내역으로 수정 재입력함"))
        self.assertEqual(c["parse_issues"],[])
        self.assertEqual(c["events"][0]["event_type"],"PARSE_ISSUES_RESOLVED")

    def test_rule_snapshot_does_not_change_after_registration(self):
        before = self.create()
        self.request("POST","/rules",dict(pack_id="CITY",title="새 규정",article="제1조",text="추가 등록한 미검증 규정입니다.",effective_date="2026-01-01",version="2"),201)
        old = self.request("GET",f"/cases/{before['id']}")
        after = self.create()
        self.assertEqual(old["rule_snapshot"],before["rule_snapshot"])
        self.assertEqual(len(after["rule_snapshot"]),len(before["rule_snapshot"])+1)

    def test_rule_period_and_conflict(self):
        base = dict(pack_id="CITY",title="기간 테스트",article="제1조",text="기간 경계가 있는 합성 규정 조항입니다.",effective_date="2026-10-16",expiry_date="2026-10-17",version="2")
        self.request("POST","/rules",base,201)
        self.request("POST","/rules",{**base,"version":"3"},201)
        c = self.create()
        codes = [f["code"] for f in c["review"]["findings"]]
        self.assertIn("RULE_CHANGE",codes)
        self.assertIn("RULE_CONFLICT",codes)
        found = self.request("GET","/rules?organization_id=demo-city&start_date=2026-10-18&end_date=2026-10-19&q=")
        self.assertFalse(any(r["title"]=="기간 테스트" for r in found["rules"]))

    def test_draft_immutable_and_csv_formula_safe(self):
        c = self.evidence(self.create(destination="=1+1"),"10/15 08:14 =가맹점 100원")
        c = self.decide(c,reason="=1+1")
        d = self.request("POST",f"/cases/{c['id']}/drafts",dict(version=c["version"]),201)
        c = self.decide(c,decision="exclude")
        saved = self.request("GET",f"/drafts/{d['id']}")
        self.assertEqual(saved["snapshot"]["review"]["candidate_total"],100)
        response = self.client.get(d["csv_url"])
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))
        cells = [cell for row in csv.reader(io.StringIO(response.content.decode("utf-8-sig"))) for cell in row]
        self.assertIn("'=1+1",cells)
        self.assertIn("'=가맹점",cells)

    def test_reason_required(self):
        c = self.evidence(self.create(),"10/15 코레일 100원")
        self.decide(c,reason="",status=422)

    def test_unknown_case_and_empty_draft(self):
        self.request("GET","/cases/unknown",status=404)
        c=self.create()
        self.request("POST",f"/cases/{c['id']}/drafts",dict(version=c["version"]),422)

    def test_print_draft_escapes_input(self):
        c=self.evidence(self.create(destination="<script>bad()</script>"),"10/15 코레일 100원")
        d=self.request("POST",f"/cases/{c['id']}/drafts",dict(version=c["version"]),201)
        response=self.client.get(d["json_url"]+"/print")
        self.assertEqual(response.status_code,200)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;",response.text)
        self.assertNotIn("<script>",response.text)
        self.assertIn("보류",response.text)
        self.assertIn("미산정",response.text)


if __name__ == "__main__":
    unittest.main()
