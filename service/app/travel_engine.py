"""결정적 파싱·매칭·검토. 법정 지급액을 계산하거나 증빙 진위를 인증하지 않는다."""
from __future__ import annotations

import hashlib
import re
from datetime import date

LABELS = {"transport": "교통", "lodging": "숙박", "meal": "식비", "other": "기타"}
DATE_RE = re.compile(r"(?<!\d)(?:(\d{4})[-./])?(\d{1,2})[-./](\d{1,2})(?!\d)")
TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")
MONEY_RE = re.compile(r"(?<![\d,.-])(\d{1,3}(?:,\d{3})+|\d+)\s*원(?![가-힣])")


def classify(merchant: str) -> str:
    for category, pattern in (("transport", r"코레일|KTX|SRT|철도|항공|고속버스"),
                              ("lodging", r"호텔|모텔|숙박|리조트"),
                              ("meal", r"식당|음식|식사|구내식당")):
        if re.search(pattern, merchant, re.I):
            return category
    return "other"


def extract_situation(text: str) -> dict:
    """지원하는 명시적 표현만 추출. 모르는 날짜·지명은 만들지 않는다."""
    result = {"destination": "", "purpose": "", "start_date": "", "end_date": ""}
    city = re.search(r"([가-힣]{2,12}?)(?:으로|로)\s*(?:\d+박\s*\d+일\s*)?(?:교육|회의|출장)", text)
    if city:
        result["destination"] = city.group(1)
    for purpose in ("교육", "회의", "점검", "행사"):
        if purpose in text:
            result["purpose"] = purpose
            break
    dates = []
    for match in DATE_RE.finditer(text):
        if not match[1]:
            continue
        try:
            dates.append(date(int(match[1]), int(match[2]), int(match[3])).isoformat())
        except ValueError:
            continue
    if dates:
        result["start_date"] = dates[0]
    if len(dates) > 1:
        result["end_date"] = dates[1]
    duration = re.search(r"(\d+)박\s*(\d+)일", text)
    return {"intent": "travel_settlement" if "출장" in text or "정산" in text else "unknown",
            "mode": "deterministic", "fields": result,
            "duration_text": duration.group(0) if duration else "",
            "missing_fields": [k for k, v in result.items() if not v],
            "notice": "규칙 기반 추출 결과입니다. 날짜와 출장정보를 확인한 뒤 저장하세요."}


def infer_date(match, start: date, end: date) -> date:
    if match[1]:
        return date(int(match[1]), int(match[2]), int(match[3]))
    candidates = []
    for year in range(start.year - 1, end.year + 2):
        try:
            candidates.append(date(year, int(match[2]), int(match[3])))
        except ValueError:
            pass
    if not candidates:
        raise ValueError("존재하지 않는 날짜")
    distance = lambda d: min(abs((d - start).days), abs((d - end).days))
    ranked = sorted(candidates, key=distance)
    if len(ranked) > 1 and distance(ranked[0]) == distance(ranked[1]):
        raise ValueError("연도 불명확: 연도를 포함해 입력하세요")
    return ranked[0]


def parse_evidence(text: str, start: date, end: date, source: str) -> tuple[list[dict], list[dict]]:
    rows, issues = [], []
    # SMS의 머리말은 건너뛰되, 거래처럼 보이는 불완전한 줄은 반드시 남긴다.
    for no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line in ("[카드]", "[Web발신]", "[전자영수증]"):
            continue
        dm, tm = DATE_RE.search(line), TIME_RE.search(line)
        amounts = list(MONEY_RE.finditer(line))
        if not dm or len(amounts) != 1:
            issues.append({"line": no, "message": "날짜와 거래금액 1개를 한 줄에 입력하세요. 누계·잔액은 별도로 제거하세요."})
            continue
        am = amounts[0]
        try:
            if re.search(r"\d{1,2}:\d{2}", line) and not tm:
                raise ValueError("존재하지 않는 시각")
            day = infer_date(dm, start, end)
            amount = int(am[1].replace(",", ""))
            if not 0 < amount <= 1_000_000_000:
                raise ValueError("금액 범위 오류")
            if am.start() and line[am.start()-1] in "-,.":
                raise ValueError("음수·소수 금액은 지원하지 않습니다")
            # 가맹점은 날짜/시간 뒤, 금액 앞에 있는 표준 붙여넣기 형식으로 한정한다.
            merchant = line[max(dm.end(), tm.end() if tm else 0):am.start()].strip(" []\t")
            merchant = re.sub(r"승인취소|취소|승인|일시불", "", merchant).strip()
            if not merchant or len(merchant) > 150:
                raise ValueError("가맹점 확인 필요")
        except ValueError as exc:
            issues.append({"line": no, "message": str(exc)})
            continue
        cancelled = "취소" in line
        clock = tm.group(0).zfill(5) if tm else ""
        merchant_key = re.sub(r"\s+", "", merchant).lower()
        normalized = f"{day}|{clock}|{merchant_key}|{amount}|{cancelled}"
        rows.append({"transaction_date": day.isoformat(), "transaction_time": clock,
                     "merchant": merchant, "amount": amount, "category": classify(merchant),
                     "source_type": source, "fingerprint": hashlib.sha256(normalized.encode()).hexdigest(),
                     "cancelled": int(cancelled)})
    return rows, issues


def evaluate(trip: dict, rows: list[dict], rules: list[dict], parse_issues: list[dict]) -> dict:
    evaluated, findings = [], []
    total = 0
    by_category = {k: 0 for k in LABELS}
    for row in rows:
        flags = []
        if not trip["start_date"] <= row["transaction_date"] <= trip["end_date"]:
            flags.append("출장기간 외 거래")
        if row["category"] in ("other", "meal"):
            flags.append("용도·별도 지급 여부 확인")
        same = [r for r in rows if r["id"] != row["id"] and r["merchant"] == row["merchant"]
                and r["amount"] == row["amount"] and r["transaction_date"] == row["transaction_date"]
                and not r["cancelled"]]
        if same and not row["cancelled"]:
            flags.append("같은 날 동일 가맹점·금액 중복 후보")
        cancellation_related = bool(row["cancelled"] or any(
            r["cancelled"] and r["merchant"] == row["merchant"] and r["amount"] == row["amount"] for r in rows))
        if cancellation_related:
            flags.append("취소 또는 취소 연관 거래: 승인내역 대조 필요")
        included = row["decision"] == "include" and not cancellation_related
        if included:
            total += row["amount"]
            by_category[row["category"]] += row["amount"]
        evaluated.append({**row, "included": included, "flags": flags,
                          "evidence_state": "IDENTIFIED", "official_verification": False})
    if parse_issues:
        findings.append({"code": "PARSE", "message": f"해석하지 못한 줄 {len(parse_issues)}개를 수정해 다시 입력하세요."})
    if not rows:
        findings.append({"code": "EMPTY", "message": "증빙 거래가 없습니다. 결제내역을 입력하세요."})
    pending = sum(r["decision"] == "pending" for r in rows)
    if pending:
        findings.append({"code": "PENDING", "message": f"거래 {pending}건의 포함·제외를 확인하세요."})
    if trip["overnight"] and not any(r["category"] == "lodging" and r["included"] for r in evaluated):
        findings.append({"code": "LODGING", "message": "숙박 있음으로 입력했으나 포함된 숙박 거래가 없습니다. 제공 숙박 여부와 증빙을 확인하세요."})
    if any(r["included"] for r in evaluated):
        findings.append({"code": "DOCUMENT", "message": "붙여넣은 거래는 진위 미검증입니다. 공식 영수증·승차권 등 인정 증빙을 별도로 준비하세요."})
    if not rules:
        findings.append({"code": "NO_RULE", "message": "해당 기간에 유효한 규정이 없습니다. 지급 판단은 보류하세요."})
    if any(r["effective_date"] > trip["start_date"] or (r["expiry_date"] and r["expiry_date"] <= trip["end_date"]) for r in rules):
        findings.append({"code": "RULE_CHANGE", "message": "출장 중 규정 유효기간 경계가 있습니다. 날짜별 적용을 담당자가 검토하세요."})
    conflicts = {}
    for r in rules:
        conflicts.setdefault((r["pack_id"], r["title"], r["article"]), []).append(r)
    if any(len(v) > 1 for v in conflicts.values()):
        findings.append({"code": "RULE_CONFLICT", "message": "같은 규정·조문에 중첩된 버전이 있습니다. 담당자 검토가 필요합니다."})
    return {"transactions": evaluated, "candidate_total": total, "by_category": by_category,
            "payable_amount": None, "findings": findings,
            "next_actions": [f["message"] for f in findings] + ["기관별 실제 규정·한도·감액 조건 확인", "정산 초안과 증빙을 기존 출장·회계시스템에서 최종 검토·제출"],
            "status": "검토 중" if pending or parse_issues else "초안 준비 가능 · 담당자 확인 필요"}
