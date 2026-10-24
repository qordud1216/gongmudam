"""기한 계산과 날짜 인식.

절차 카드의 각 단계는 다음 형식의 기한 규칙을 가질 수 있다.
    {"base": "출장 종료일", "offset": 5, "unit": "업무일"}   # 기준일 다음 업무일부터 5업무일째
    {"base": "행사일", "offset": -14, "unit": "일"}           # 기준일 14일 전
기한은 LLM이 아니라 이 모듈이 결정적으로 계산한다 (모델을 바꿔도 결과가 같다).
공휴일 목록은 holidays.json 에 있으며 관리자가 고칠 수 있다.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

HOLIDAY_PATH = Path(__file__).resolve().parent / "holidays.json"
_holidays: dict[str, str] | None = None
WEEKDAYS = "월화수목금토일"


def holidays() -> dict[str, str]:
    global _holidays
    if _holidays is None:
        raw = json.loads(HOLIDAY_PATH.read_text(encoding="utf-8"))
        _holidays = {k: v for k, v in raw.items() if not k.startswith("_")}
    return _holidays


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in holidays()


def add_business_days(d: date, n: int) -> date:
    step = 1 if n >= 0 else -1
    left = abs(n)
    cur = d
    while left:
        cur += timedelta(days=step)
        if is_business_day(cur):
            left -= 1
    return cur


def _before_business_day(d: date) -> date:
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def evaluate(rule: dict | None, base_values: dict[str, date]) -> tuple[date | None, list[str]]:
    """기한과 함께, 예외 조항을 적용했을 때 그 사실을 알리는 문장을 돌려준다.
    rule["month_cap"] = {"month": 12, "day": 26, "basis": "..."}:
        기준일이 그 달에 있으면 기한을 그 달 day 일보다 늦지 않게 당긴다(예: 12월 출장은 12월 26일까지)."""
    if not rule or not rule.get("base"):
        return None, []
    base = base_values.get(rule["base"])
    if base is None:
        return None, []
    off = int(rule.get("offset") or 0)
    notes: list[str] = []
    if rule.get("unit") == "업무일":
        due = add_business_days(base, off)
    else:
        due = base + timedelta(days=off)
        # 달력일 기한이 휴일에 걸리면 앞당겨 안내한다 (늦지 않게 하는 쪽을 택함)
        if rule.get("adjust", "before") == "before" and off != 0:
            due = _before_business_day(due)
    cap = rule.get("month_cap")
    if cap and base.month == int(cap["month"]):
        limit = date(base.year, int(cap["month"]), int(cap["day"]))
        where = f"({cap['basis']})" if cap.get("basis") else ""
        if due > limit:
            adj = _before_business_day(limit)
            msg = f"{cap['month']}월에 끝난 경우 {cap['month']}월 {cap['day']}일까지 내야 하므로{where} 기한을 앞당겼습니다."
            if adj != limit:
                msg += f" {cap['day']}일이 주말·휴일이라 앞 업무일인 {fmt(adj)}로 안내합니다."
            due = adj
            if base <= limit:
                notes.append(msg)
        if base > limit:
            notes.append(f"{rule['base']}이 {cap['month']}월 {cap['day']}일 이후라 규정상 기한이 이미 지났습니다{where}. 담당 부서에 바로 문의하세요.")
    return due, notes


def apply_rule(rule: dict | None, base_values: dict[str, date]) -> date | None:
    return evaluate(rule, base_values)[0]


def rule_text(rule: dict | None) -> str:
    if not rule or not rule.get("base"):
        return ""
    off = int(rule.get("offset") or 0)
    unit = rule.get("unit") or "일"
    if off == 0:
        text = f"{rule['base']} 당일"
    else:
        text = f"{rule['base']} {abs(off)}{unit} {'후' if off > 0 else '전'}"
    cap = rule.get("month_cap")
    if cap:
        text += f" ({cap['month']}월은 {cap['day']}일까지)"
    return text


def fmt(d: date | None) -> str:
    if d is None:
        return ""
    return f"{d.year}. {d.month}. {d.day}.({WEEKDAYS[d.weekday()]})"


def dday(due: date | None, today: date) -> dict:
    if due is None:
        return {"label": "기한 없음", "state": "none", "days": None}
    n = (due - today).days
    if n < 0:
        return {"label": f"{-n}일 지남", "state": "overdue", "days": n}
    if n == 0:
        return {"label": "오늘까지", "state": "today", "days": 0}
    state = "soon" if n <= 3 else "ok"
    return {"label": f"D-{n}", "state": state, "days": n}


# ------------------------------------------------------------------ 문장 속 날짜 인식
_REL = {"그저께": -2, "그제": -2, "어제": -1, "작일": -1, "오늘": 0, "금일": 0, "내일": 1, "명일": 1, "모레": 2, "글피": 3}
# 날짜를 하나로 정할 수 없는 상대 표현 (모델 설명에서 기한을 말할 때 쓰면 검증할 수 없다)
VAGUE_REL = re.compile(r"이틀|사흘|나흘|닷새|익일|이번\s*주|다음\s*주|금주|차주|내주|주말|주중|월말|이달\s*말|이번\s*달|다음\s*달|이달|내달|익월")
REL_WORDS = set(_REL)
_PATTERNS = [
    re.compile(r"(?P<y>20\d{2})\s*[.\-/년]\s*(?P<m>\d{1,2})\s*[.\-/월]\s*(?P<d>\d{1,2})\s*일?"),
    re.compile(r"(?<!\d)(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"),
    re.compile(r"(?<![\d.])(?P<m>\d{1,2})\s*[/.]\s*(?P<d>\d{1,2})(?![\d.])"),
]
_WEEKDAY_REF = re.compile(r"(지난주|이번\s*주|다음\s*주)\s*([월화수목금토일])요일")
_N_DAYS = re.compile(r"(\d{1,2})\s*일\s*(전|후|뒤)")


def find_dates(text: str, today: date) -> list[dict]:
    """문장에서 날짜 표현을 찾아 [{"date": date, "text": 원문, "pos": 위치}] 로 돌려준다."""
    found: list[dict] = []
    taken: list[tuple[int, int]] = []

    def add(d: date, m: re.Match) -> None:
        s, e = m.span()
        if any(not (e <= a or s >= b) for a, b in taken):
            return
        taken.append((s, e))
        found.append({"date": d, "text": m.group(0).strip(), "pos": s})

    for i, pat in enumerate(_PATTERNS):
        for m in pat.finditer(text):
            try:
                y = int(m.groupdict().get("y") or today.year)
                d = date(y, int(m.group("m")), int(m.group("d")))
            except ValueError:
                continue
            if not m.groupdict().get("y") and (d - today).days > 200:
                d = d.replace(year=d.year - 1)  # "12월 28일"을 1월에 말하면 작년으로 본다
            add(d, m)
    for m in _WEEKDAY_REF.finditer(text):
        week = {"지난주": -1, "이번주": 0, "다음주": 1}[re.sub(r"\s", "", m.group(1))]
        monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week)
        add(monday + timedelta(days=WEEKDAYS.index(m.group(2))), m)
    for m in _N_DAYS.finditer(text):
        n = int(m.group(1))
        add(today + timedelta(days=n if m.group(2) != "전" else -n), m)
    for word, off in _REL.items():
        # '작일·명일·금일'은 '시작일·설명일·지금일'처럼 다른 낱말 끝에도 나오므로 낱말 첫머리일 때만 본다
        pat = rf"(?<![가-힣]){word}" if word in ("작일", "명일", "금일") else word
        for m in re.finditer(pat, text):
            add(today + timedelta(days=off), m)
    found.sort(key=lambda x: x["pos"])
    return found


def parse_iso(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
