"""상황 안내: "출장 다녀와서 정산해야 해요" → 절차 카드 선택 + 단계별 기한 + 필요 서식 + 근거 조문.

흐름
1) 검색: 절차 카드와 규정 조문을 BM25 로 찾는다 (모든 모드 공통).
2) 판단: LLM 이 연결돼 있으면 후보 중 카드와 근거 조문을 고르게 한다.
   LLM 이 없거나 실패하면 검색 1순위 카드로 안내한다.
3) 계산: 기한·D-day 는 deadlines 모듈이 결정적으로 계산한다.
4) 본문: 안내 본문(answer)은 언제나 카드의 단계·서식·근거·조건으로 만든 규칙 기반 문장이다.
   모델이 쓴 문장은 본문에 넣지 않고, 기한·날짜 문장을 뺀 뒤 참고용 'AI 보충 설명'(ai_note)으로만 따로 낸다.
   LLM 이 인용한 조문 ID 중 실제로 후보에 없는 것은 버린다.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date

from . import config, deadlines, llm, store
from .search import BM25

LAYER_RANK = {"개인": 0, "기관": 1, "공통": 2}


def _card_text(c: dict) -> str:
    steps = " ".join(s.get("title", "") + " " + s.get("detail", "") for s in c["steps"])
    return " ".join([c["title"]] * 3 + [c["category"]] * 2 + [c.get("keywords", "")] * 3 + [c.get("summary", ""), steps])


def search_cards(query: str, layers: list[str] | None = None, k: int = 3) -> list[tuple[dict, float]]:
    cards = [c for c in store.list_cards() if not layers or c["layer"] in layers]
    if not cards:
        return []
    bm = BM25([_card_text(c) for c in cards])
    res = [(cards[i], s) for i, s in bm.top(query, k=k + 2, min_score=0.5)]
    # 같은 점수대에서는 기관 > 공통 순으로 앞에 둔다 (기관 규정이 공통 규정을 보충·우선)
    res.sort(key=lambda x: (-round(x[1], 0), LAYER_RANK.get(x[0]["layer"], 9)))
    return res[:k]


def search_chunks(query: str, layers: list[str] | None = None, k: int = 6) -> list[tuple[dict, float]]:
    chunks = [c for c in store.all_chunks(layers) if c["kind"] != "서식"]
    if not chunks:
        return []
    bm = BM25([f"{c['title']} {c['label']} {c['text']}" for c in chunks])
    return [(chunks[i], s) for i, s in bm.top(query, k=k, min_score=1.0)]


# ------------------------------------------------------------------ 카드 → 실행 계획
def detect_conditions(card: dict, query: str) -> list[str]:
    """질문에 '교대근무' 같은 조건 낱말이 있으면 해당 단계의 예외(variants)를 적용한다."""
    q = query or ""
    flat = re.sub(r"\s+", "", q)
    found = []
    for s in card.get("steps") or []:
        for v in s.get("variants") or []:
            if any(k in q or re.sub(r"\s+", "", k) in flat for k in v.get("keywords") or []):
                found.append(v["id"])
    return list(dict.fromkeys(found))


def _pick_variant(step: dict, applied: set[str]) -> tuple[dict | None, list[dict]]:
    """적용할 예외 조건을 고른다. 돌려주는 값: (적용 조건, 충돌한 조건 목록).
    여러 조건이 함께 해당되면 priority 가 가장 높은 하나만 적용한다(예: 질병·사고 > 교대근무).
    가장 높은 priority 가 둘 이상이면 고르지 않고 충돌로 돌려준다."""
    cands = [v for v in step.get("variants") or [] if v.get("id") in applied]
    if len(cands) <= 1:
        return (cands[0] if cands else None), []
    top = max(int(v.get("priority") or 0) for v in cands)
    best = [v for v in cands if int(v.get("priority") or 0) == top]
    return (best[0], []) if len(best) == 1 else (None, cands)


def build_plan(card: dict, base_values: dict[str, date], today: date, conditions: list[str] | None = None) -> dict:
    forms = {f["id"]: f for f in store.list_forms()}
    applied = set(conditions or [])
    reviewed = card.get("reviewed_at") or ""
    warnings: list[str] = []
    if card.get("status") != "확정":
        warnings.append("이 절차 카드는 아직 '초안'입니다. 담당자 확인 후 확정하세요.")
    steps = []
    next_idx = None
    for i, s in enumerate(card["steps"]):
        # 예외 조건(예: 교대근무자)을 적용하면 그 조건의 기한·설명을 쓰고, 아니면 해당자일 때의 기한을 함께 알린다
        variant, conflict = _pick_variant(s, applied)
        if conflict:
            # 우선순위를 정하지 않은 조건이 함께 해당되면 어느 기한도 단정하지 않는다
            rule, due, notes = None, None, []
            parts = []
            for v in conflict:
                vdue, _ = deadlines.evaluate(v.get("deadline"), base_values)
                parts.append(f"'{v['label']}'은(는) {deadlines.fmt(vdue) + '까지' if vdue else v.get('note') or '기한이 다름'}"
                             f"({v.get('basis', '')})")
            warnings.append(f"{i + 1}단계: 조건이 여러 개 함께 해당되어 기한을 하나로 정할 수 없습니다. "
                            + ", ".join(parts) + ". 담당 부서에 확인하세요.")
        else:
            rule = variant.get("deadline") if variant else s.get("deadline")
            due, notes = deadlines.evaluate(rule, base_values)
        warnings += [f"{i + 1}단계: {n}" for n in notes]
        if variant:
            warnings.append(f"{i + 1}단계: '{variant['label']}' 조건을 적용했습니다({variant.get('basis', '')}).")
            for v in s.get("variants") or []:
                if v is not variant and v.get("id") in applied:
                    vdue, _ = deadlines.evaluate(v.get("deadline"), base_values)
                    when = f"{deadlines.fmt(vdue)}까지" if vdue else (v.get("note") or "다른 기한")
                    warnings.append(f"{i + 1}단계: '{v['label']}' 조건도 해당되지만 "
                                    f"{variant.get('priority_note') or '우선 적용 조건이 있어'} "
                                    f"'{variant['label']}' 기준으로 안내합니다. '{v['label']}' 기한({when}, {v.get('basis', '')})은 "
                                    "적용하지 않았습니다. 사정이 다르면 담당 부서에 확인하세요.")
        for v in [] if variant or conflict else s.get("variants") or []:
            vdue, _ = deadlines.evaluate(v.get("deadline"), base_values)
            when = f"{deadlines.fmt(vdue)}까지입니다" if vdue else (v.get("note") or "기한이 다릅니다")
            warnings.append(f"{i + 1}단계 · {v['label']}: {when}({v.get('basis', '')}). "
                            "해당하면 질문에 그 사정을 함께 적어 주세요.")
        basis = []
        for b in s.get("basis") or []:
            r = store.resolve_basis(b.get("doc_id", ""), b.get("label", ""))
            if r is None:
                basis.append({"doc_id": b.get("doc_id"), "label": b.get("label"), "missing": True,
                              "title": b.get("title", ""), "text": ""})
                warnings.append(f"{i + 1}단계 근거 '{b.get('label')}'를 현재 등록 문서에서 찾을 수 없습니다(삭제·개정 확인 필요).")
                continue
            changed = bool(reviewed and r["updated_at"] > reviewed)
            if changed:
                warnings.append(f"{i + 1}단계 근거 문서 '{r['title']}'가 카드 확정({reviewed[:10]}) 이후 수정되었습니다. 절차를 다시 확인하세요.")
            basis.append({"chunk_id": r["id"], "doc_id": r["doc_id"], "label": r["label"], "loc": r["loc"],
                          "title": r["title"], "layer": r["layer"], "text": r["text"], "changed": changed})
        dd = deadlines.dday(due, today)
        if next_idx is None and due is not None and due >= today:
            next_idx = i
        steps.append({
            "no": i + 1, "title": s.get("title", ""), "detail": (variant or {}).get("detail") or s.get("detail", ""),
            "tip": s.get("tip", ""), "variant": variant["label"] if variant else None,
            "rule": " ".join(x for x in (f"[{variant['label']}]" if variant else "", deadlines.rule_text(rule)) if x), "deadline": rule,
            "due": due.isoformat() if due else None, "due_text": deadlines.fmt(due), "dday": dd,
            "forms": [{"id": fid, "name": forms[fid]["name"]} for fid in s.get("forms") or [] if fid in forms],
            "basis": basis,
        })
    if next_idx is None and steps and not any(s["due"] for s in steps):
        next_idx = 0  # 기준일을 모르면 첫 단계부터 안내한다
    used = {st["deadline"]["base"] for st in steps if st.get("deadline") and st["deadline"].get("base")}
    missing_bases = [b for b in card.get("base_dates") or [] if b in used and b not in base_values]
    return {
        "card": {k: card[k] for k in ("id", "title", "category", "layer", "summary", "status", "notes", "base_dates")},
        "base_values": {k: v.isoformat() for k, v in base_values.items()},
        "missing_bases": missing_bases,
        "today": today.isoformat(),
        "conditions": sorted({st_v["id"] for st in card["steps"] for st_v in st.get("variants") or [] if st_v["id"] in applied}),
        "steps": steps,
        "next_index": next_idx,
        "warnings": list(dict.fromkeys(warnings)),
    }


def guess_base_values(card: dict, query: str, today: date) -> dict[str, date]:
    """문장 속 날짜를 카드의 기준일에 대응시킨다.
    - '10월 13일부터 15일까지 출장' 처럼 날짜가 기준일 수만큼 있으면 순서대로 맞춘다.
    - 날짜가 더 적으면 날짜 주변 낱말(예: '납품', '행사')이 기준일 이름과 겹치는 쪽에 둔다.
      겹치는 낱말이 같으면 '종료'가 들어간 기준일(이미 끝난 일)을 고른다."""
    bases = card.get("base_dates") or []
    found = [(f["date"], f["pos"], len(f["text"])) for f in deadlines.find_dates(query, today)]
    m = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일?\s*(?:부터|~|-)\s*(\d{1,2})\s*일", query)
    if m:
        try:
            y = found[0][0].year if found else today.year
            found = [(date(y, int(m.group(1)), int(m.group(2))), m.start(), 0),
                     (date(y, int(m.group(1)), int(m.group(3))), m.end(), 0)]
        except ValueError:
            pass
    if not bases or not found:
        return {}
    if len(bases) == 1:
        return {bases[0]: found[-1][0]}
    if len(found) >= len(bases):
        return {b: f[0] for b, f in zip(bases, found)}
    out: dict[str, date] = {}
    for d, pos, ln in found:
        window = query[max(0, pos - 10): pos + ln + 14]
        def score(b: str) -> tuple:
            words = [w.removesuffix("일") for w in b.split() if len(w.removesuffix("일")) >= 2]
            return (sum(w in window for w in words), "종료" in b, bases.index(b))
        free = [b for b in bases if b not in out]
        if free:
            out[max(free, key=score)] = d
    return out


# ------------------------------------------------------------------ LLM 프롬프트
SYSTEM = (
    "당신은 공공기관 서무 업무를 돕는 비서입니다. 반드시 제공된 절차 카드와 규정 조문만 근거로 답합니다. "
    "근거에 없는 내용은 지어내지 말고 '등록된 규정에서 확인되지 않음'이라고 말합니다. "
    "단계별 기한은 시스템이 계산해 화면에 따로 표시하므로 답변에 기한·날짜·요일·일수와 '오늘'·'내일' 같은 시점 표현을 쓰지 말고, 필요 서식·증빙·결재 경로·주의점을 설명합니다. "
    "출력은 JSON 하나만 냅니다."
)


def _plan_lines(plan: dict) -> list[str]:
    """모델에게는 단계와 서식만 준다. 기한·기준일은 주지 않는다(모델이 날짜를 옮겨 쓰지 않게, 기한은 계산 카드가 맡는다)."""
    out = []
    for s in plan["steps"]:
        forms = ", ".join(f["name"] for f in s["forms"])
        cond = f" — 적용 조건: {s['variant']}" if s.get("variant") else ""
        out.append(f"  {s['no']}. {s['title']}" + (f" — 서식: {forms}" if forms else "") + cond)
    return out


def _llm_prompt(query: str, today: date, cards: list[dict], plans: dict[str, dict], chunks: list[dict]) -> str:
    payload = {
        "question": query,
        "cards": [
            {"id": c["id"], "title": c["title"], "category": c["category"],
             "summary": c.get("summary", ""), "steps": _plan_lines(plans[c["id"]])}
            for c in cards
        ],
        "source_chunks": [
            {"id": ch["id"], "title": ch["title"], "label": ch["label"],
             "text": re.sub(r"\s+", " ", ch["text"])[:350]}
            for ch in chunks
        ],
        "allowed_card_ids": [c["id"] for c in cards],
        "allowed_citation_ids": [ch["id"] for ch in chunks],
    }
    contract = (
        "응답 계약: JSON 객체 하나만 출력한다. card_id는 allowed_card_ids 중 실제로 가장 맞는 ID를 그대로 쓰고, "
        "맞는 카드가 없으면 null을 쓴다. ID 앞에 'id='를 붙이거나 카드 제목을 ID 대신 쓰지 않는다. "
        "answer는 존댓말 한국어 2개의 짧은 문장으로 작성하고 절차, 서식, 증빙, 결재·제출 경로 또는 주의점만 안내한다. "
        "날짜, 요일, 기한, 기간, 일수, 오늘·내일 등 시점 표현은 쓰지 않는다. 근거에 없는 사실은 만들지 않는다. "
        "cited에는 answer에 실제 사용한 allowed_citation_ids만 넣는다. 출력 필드는 card_id, answer, cited다."
    )
    return json.dumps(payload, ensure_ascii=False) + "\n\n" + contract


def _tidy(text: str) -> str:
    """일부 모델이 '11 월 20 일', '제 4 조'처럼 띄워 쓰는 것을 바로잡는다."""
    text = re.sub(r"(\d)\s+(월|일|업무일|조|항|년|원|쪽)", r"\1\2", text)
    return re.sub(r"제\s+(\d+)\s*조", r"제\1조", text)


# AI 보충 설명(ai_note)에서 기한·일정을 말하는 문장의 표지. 날짜 값이 맞는지 따지지 않고, 하나라도 있으면 문장째 뺀다.
# 본문(answer)에는 모델 문장이 들어가지 않으므로 이 필터는 참고용 보충 설명에만 쓴다(오탐은 감수한다).
_SCHEDULE = re.compile("|".join([
    # 기한·일정 낱말
    r"기한|마감|까지|이내|이전|이후|직전|직후|전까지|늦어도|언제|며칠|당일|즉시|신속|조속|지체\s*없이|곧바로|바로|"
    r"서둘|빨리|당장|도래|만료|경과|기일|시한|일정|기간|데드라인|디데이|미리|제때|업무일|영업일|근무일|번째|째",
    # 숫자 날짜·일수·시각 (숫자가 든 문장은 _NOT_PLAIN 이 먼저 지우지만, 표지로도 남겨 둔다)
    r"\d+\s*(?:일|월|주|업무일|영업일|근무일|년|개월|시|분)",
    r"\d{1,4}\s*[./\-]\s*\d{1,2}",
    r"[Dd]\s*[-+]\s*\d|[Dd]\s*-?\s*day",
    # 한글 수사 일수·기간 ('하루', '사흘', '삼일', '일주일', '한 달')
    r"하루|이틀|사흘|나흘|닷새|엿새|이레|여드레|아흐레|열흘|보름|수일|며칠|일주일|(?:한|두|세|석|네|넉)\s*(?:주|달)",
    r"(?<![가-힣])[일이삼사오육칠팔구십]{1,4}(?:일|주일|업무일|개월)(?![가-힣])|"
    r"(?<![가-힣])[일이삼사오육칠팔구십]{1,4}(?:일|주일|업무일|개월)(?=[은는이가을를에로까도만입째차])",
    # 고유어·한자어 날짜 ('시월 스무날', '초사흘', '그믐', '섣달', '하순')
    r"스무|스물|열하루|열이틀|초하루|초(?:이틀|사흘|나흘|닷새|엿새|이레|여드레|아흐레|열흘)|그믐|날짜\s*(?:에|까지|안)|"
    r"정월|동짓달|섣달|(?:일|이|삼|사|오|유|육|칠|팔|구|시|십|십일|십이)월|상순|초순|중순|하순",
    # 요일 (전체 이름, 괄호 속 한 글자 '(목)', '월~금')
    r"[월화수목금토일]요일|\(\s*[월화수목금토일]\s*\)|[월화수목금토일]\s*[~∼\-]\s*[월화수목금토일](?![가-힣])|주말|주중|평일|공휴일|휴일",
    # 상대 날짜 ('작일·명일·금일·익일'은 '시작일·설명일'처럼 낱말 끝에도 나오므로 낱말 첫머리만)
    r"오늘|내일|모레|글피|어제|그제|그저께|(?<![가-힣])(?:작일|명일|금일|익일|익월|익주|익년|익영업일|익업무일|전날)",
    r"차주|금주|내주|전주|내달|이달|금월|차월|월말|월초|연말|연초|지난\s*(?:주|달)|이번\s*(?:주|달)|다음\s*(?:주|달|날)",
    r"오전|오후|아침|저녁|점심|새벽|지금|곧|금방|나중|이따",
    # 날짜 숫자 없이 시점을 말하는 '날' ('복귀한 날', '그날까지') — '날인·날짜'는 제외
    r"날(?:에|까지|부터|로|이|은|을|에는)?(?![가-힣])",
    # 독립된 '전·후·뒤' ('출장 전에', '작성한 후', '하루 뒤', '전 업무일') — '전자결재·후속·사전'은 제외
    r"(?<![가-힣])(?:전|후|뒤)(?:에|까지|부터|로|이|에는)?(?![가-힣])",
]))
# 한글·공백·기본 문장부호 밖의 글자(숫자·영문·한자·기호)가 하나라도 있으면 그 문장은 뺀다 ('Tue', 'D−2', '21日')
_NOT_PLAIN = re.compile(r"[^가-힣\s.,!?·:;'\"‘’“”()「」『』…]")
_INVISIBLE = re.compile(r"[\u200b-\u200f\u2060\ufeff\u00ad]")
_DASHES = re.compile(r"[\u2010-\u2015\u2212\u2043\ufe58\ufe63\uff0d]")  # 붙임표·빼기 기호 → '-'
_SENT_END = re.compile(r"(?<=[^\d\s][.!?。])\s+|\s*\n+\s*")  # '2026. 10. 21.' 속 마침표에서는 자르지 않는다


def _normalize(text: str) -> str:
    return _DASHES.sub("-", _INVISIBLE.sub("", unicodedata.normalize("NFKC", text)))


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _SENT_END.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def _is_schedule(sent: str) -> bool:
    """기한·날짜를 말할 수 있는 문장인지 본다. 띄어 써서 피하는 경우('차 주', '내 일')를 위해 공백을 지운 문장도 같은 표지로 본다."""
    sent = _normalize(sent)
    return bool(_NOT_PLAIN.search(sent) or _SCHEDULE.search(sent) or _SCHEDULE.search(re.sub(r"\s+", "", sent)))


# 보충 설명 허용 목록. 위 표지(블랙리스트)는 '낼·수욜'처럼 새 표현이 나올 때마다 빠져나가므로,
# 문장의 모든 어절이 아래 절차 명사(+조사 하나 또는 정해진 동사 어미) 또는 고정 어절일 때만 남긴다. 모르는 어절이 하나라도 있으면 문장째 뺀다.
# 7차 감사: 시점·순서·빈도·정도를 뜻하는 낱말(사전·사후·단계·날짜·초과·정확 등)은 명사에서 뺐고, 부사·수식어(꼭·반드시·먼저·함께·해당 등)는
# 고정 어절에서도 뺐다. 조사는 시점을 만들지 않는 격조사만 하나 허용한다('에·에서·에는·부터·까지·전·후'와 서술격 '입니다'는 받지 않는다).
# 앞뒤 순서를 만드는 연결 어미('-고·-며·-여·-서·-어', '작성하고 제출하세요')도 받지 않아, 한 문장에는 서술어가 하나만 남는다.
_NOTE_STEMS = (
    "국내출장 출장 여비 정산서 정산 서식 영수증 증빙서류 증빙 서류 자료 전자결재 결재선 결재권자 결재 문서번호 문서 번호 "
    "승인 신청서 신청 제출 작성 첨부 기재 서명 날인 확인 검토 문의 담당자 담당부서 담당 부서장 부서 상급자 "
    "기관 지침 공통 규정 조문 근거 적용 운임 숙박비 숙박 일비 식비 교통비 금액 비용 지출 실비 한도 본인 부담 "
    "대상 기차 승차권 항공권 카드 전표 결과 보고서 보고 복명 연가 복무관리시스템 복무 시스템 메뉴 화면 근무표 조정 "
    "사유서 사유 물품 구매 요구서 견적서 납품 검수 검사조서 검사 대금 지급 계약 행사 계획 참석 안내문 발송 경로 요청 "
    "절차 진행 처리 등록 원본 사본 내용 항목 주의 유의 필요 여부 누락 행정팀 회계팀 행정 회계 경우"
).split()
_NOTE_ENDINGS = (
    "하세요 하십시오 하신 하셔야 하셔도 해야 합니다 한 할 하는 하지 했는지 하는지 해주세요 "
    "된 되는 될 됩니다 되지 되었는지 받으세요 받아야 받은 받을 받습니다"
).split()
_NOTE_PARTICLES = "은 는 이 가 을 를 과 와 의 로 으로".split()
_NOTE_WORDS = set((
    "바랍니다 있습니다 없습니다 수 및 등 등을 등의 또는 "
    "필요한 필요합니다 적으세요 적습니다 적어야 붙이세요 올리세요 모으세요 "
    "받으세요 내세요 빠집니다 내려받을 없는 않는 않은 있는 지출한 등록된 통해 따르세요 "
    "대한 위한 위해 않도록 합니다 하세요 됩니다"
).split())
# 카드 제목·단계·서식 이름에서 허용 명사를 더할 때 빼는 시점·순서·빈도·정도 낱말(이 낱말이 든 카드 낱말은 쓰지 않는다)
_NOTE_BANNED = (
    "사전 사후 미리 먼저 우선 즉시 바로 곧바로 당일 익일 기간 이내 이전 이후 직전 직후 기한 마감 날짜 일자 시점 시기 "
    "순서 순차 단계 차례 다음 이번 지난 최초 최종 처음 마지막 나중 동시 수시 매번 항상 자주 반드시 가급적 되도록 최대한 "
    "이상 이하 미만 초과 정도 완료 종료 착수 개시 시작 도착 출발 복귀 귀청 일정 시한 기일 준비"
).split()
_NOTE_TRAIL = re.compile(f"(?:{'|'.join(sorted(_NOTE_PARTICLES + ['에', '에서', '에는', '에게'], key=len, reverse=True))})$")
_EOJEOL_SPLIT = re.compile(r"[\s·,/]+")
_EOJEOL_STRIP = ".,!?:;'\"‘’“”()「」『』…"


def _alt(words) -> str:
    return "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))


def _card_stems(plan: dict | None) -> list[str]:
    """선택된 카드의 제목·단계 이름·서식 이름 낱말. 끝에 붙은 조사('복무관리시스템에', '구매와')는 떼고, 시간 표지·금지 낱말이 든 것은 뺀다."""
    if not plan:
        return []
    names = [plan["card"]["title"]] + [s["title"] for s in plan["steps"]] + [f["name"] for s in plan["steps"] for f in s["forms"]]
    out = []
    for w in (w for n in names for w in re.findall(r"[가-힣]{2,}", n)):
        bare = _NOTE_TRAIL.sub("", w)
        w = bare if len(bare) >= 2 else w
        # 조사·어미를 붙인 꼴('받기'+'한' → '받기한')에도 금지 낱말이 생기지 않아야 한다
        if not _is_schedule(w) and not any(b in w + suf for b in _NOTE_BANNED for suf in ["", *_NOTE_PARTICLES, *_NOTE_ENDINGS]):
            out.append(w)
    return out


def _note_vocab(plan: dict | None) -> re.Pattern:
    """허용 어절 패턴: 허용 명사 하나 + (동사 어미 하나 | 격조사 하나)?. 명사끼리 이어 붙인 어절은 받지 않는다."""
    stems = list(_NOTE_STEMS) + _card_stems(plan)
    return re.compile(f"(?:{_alt(stems)})(?:{_alt(_NOTE_ENDINGS)}|{_alt(_NOTE_PARTICLES)})?")


def _allowed(sent: str, vocab: re.Pattern) -> bool:
    sent = re.sub(r"해\s+주세요", "해주세요", sent)  # '첨부해 주세요'의 보조 용언만 붙여 본다('작성해 제출하세요'는 받지 않는다)
    words = [w.strip(_EOJEOL_STRIP) for w in _EOJEOL_SPLIT.split(sent)]
    words = [w for w in words if w]
    return bool(words) and all(w in _NOTE_WORDS or vocab.fullmatch(w) for w in words)


def _drop_schedule(text: str, plan: dict | None = None) -> tuple[str, int]:
    """기한·날짜·일정을 말할 수 있는 문장을 모두 뺀다. 남은 문장과 뺀 문장 수를 돌려준다.
    표지에 걸리는 문장을 빼고, 남은 문장도 모든 어절이 허용 목록에 있을 때만 남긴다(정상 설명이 줄어드는 것은 감수한다)."""
    text = _normalize(text)
    spans = _sentence_spans(text)
    vocab = _note_vocab(plan)
    keep = [text[a:b].strip() for a, b in spans if not _is_schedule(text[a:b]) and _allowed(text[a:b], vocab)]
    return " ".join(keep).strip(), len(spans) - len(keep)


def _rule_answer(plan: dict | None) -> str:
    """안내 본문. 선택된 카드의 단계 이름·필요 서식·근거 조문·적용 조건으로만 만든다(모델 문장은 쓰지 않는다)."""
    if not plan:
        return "관련 규정 조문을 확인하세요."
    st = plan["steps"]
    parts = [f"'{plan['card']['title']}' 절차는 모두 {len(st)}단계입니다: "
             + ", ".join(f"{s['no']}단계 {s['title']}" for s in st) + "."]
    forms = list(dict.fromkeys(f["name"] for s in st for f in s["forms"]))
    if forms:
        parts.append(f"필요 서식은 {', '.join(forms)}입니다.")
    basis = list(dict.fromkeys(f"{b.get('title', '')} {b.get('label', '')}".strip()
                               for s in st for b in s["basis"] if not b.get("missing")))
    if basis:
        parts.append(f"근거 조문은 {', '.join(basis)}입니다.")
    conds = list(dict.fromkeys(s["variant"] for s in st if s.get("variant")))
    if conds:
        parts.append(f"적용한 조건은 {', '.join(conds)}입니다.")
    return " ".join(parts) + " 단계별 할 일은 아래 계산 결과 카드를 확인하세요."


def ask(query: str, *, today: date | None = None, layers: list[str] | None = None,
        card_id: str | None = None, base_values: dict[str, str] | None = None,
        conditions: list[str] | None = None, profile_override: dict | None = None) -> dict:
    today = today or date.today()
    query = (query or "").strip()
    card_hits = search_cards(query, layers)
    chunk_hits = search_chunks(query, layers)
    cards = [c for c, _ in card_hits]
    chunks = [c for c, _ in chunk_hits]
    chosen = store.get_card(card_id) if card_id else None
    if chosen and chosen["id"] not in {c["id"] for c in cards}:
        cards = [chosen] + cards

    def plan_for(card: dict) -> dict:
        if base_values:
            bv = {k: d for k, v in base_values.items() if (d := deadlines.parse_iso(v))}
        else:
            bv = guess_base_values(card, query, today)
        cond = conditions if conditions is not None else detect_conditions(card, query)
        return build_plan(card, bv, today, cond)

    plans = {c["id"]: plan_for(c) for c in cards}  # 기한은 모델이 아니라 여기서 결정적으로 계산한다

    profile = dict(profile_override) if profile_override is not None else config.active_profile()
    provider = llm.get_provider(profile)
    mode, notices, note, cited = "offline", [], "", []
    if provider.available and query and (cards or chunks):
        try:
            raw = provider.chat([{"role": "system", "content": SYSTEM},
                                 {"role": "user", "content": _llm_prompt(query, today, cards, plans, chunks)}],
                                max_tokens=int(profile.get("max_tokens", 700)))
            data = llm.extract_json(raw)
            if not isinstance(data, dict):
                raise llm.LLMError("모델 응답이 JSON 객체가 아님", str(raw)[:300])
            mode = "llm"
            ids = {c["id"]: c for c in cards}
            cid = data.get("card_id") if isinstance(data.get("card_id"), str) else None
            if not chosen and cid in ids:
                chosen = ids[cid]
            elif not chosen and data.get("card_id") and cards:
                chosen = cards[0]  # 후보에 없는 id 를 내면 검색 1순위로 대체
            note = _tidy(_normalize(str(data.get("answer") or ""))).strip()  # 본문에는 쓰지 않고 참고용 보충 설명으로만
            valid = {c["id"] for c in chunks}
            raw_cited = data.get("cited") if isinstance(data.get("cited"), list) else []
            cited = [x for x in raw_cited if isinstance(x, str) and x in valid]
            dropped = [x for x in raw_cited if not (isinstance(x, str) and x in valid)]
            if dropped:
                notices.append(f"모델이 존재하지 않는 근거 {len(dropped)}건을 인용해 제외했습니다.")
        except llm.LLMError as e:
            mode = "fallback"
            # 모델·서버 응답 본문은 화면에 내지 않는다(본문은 LLMError 가 로그로만 남김). 고정 문구와 오류 종류만 알린다.
            notices.append(f"모델 서버 응답 오류로 규칙 기반 안내로 전환했습니다(오류 종류: {e.kind}).")

    if chosen is None and mode != "llm" and card_hits:
        chosen = card_hits[0][0]

    plan = (plans.get(chosen["id"]) or plan_for(chosen)) if chosen else None
    summary = _offline_answer(plan, chunks)  # 기한 안내 문장은 항상 결정적으로 만든다
    # 본문은 모드가 llm 이면 언제나 규칙 기반 문장이다. 오프라인·fallback 은 지금처럼 summary 만 쓴다.
    answer = _rule_answer(plan) if mode == "llm" else ""
    ai_note, note_dropped = _drop_schedule(note, plan) if note else ("", 0)
    cited_chunks = [c for c in chunks if c["id"] in cited] if cited else []
    personal = [c for c in chunks if c["layer"] == "개인"]
    return {
        "query": query,
        "mode": mode,
        "model": profile.get("model") if mode == "llm" else None,
        "profile": profile.get("_name"),
        "notice": " ".join(notices) or None,
        "summary": summary,
        "answer": answer,
        "ai_note": ai_note or None,  # 참고용 AI 보충 설명(기한·날짜 문장 제외). 모두 빠지면 None
        "ai_note_dropped": note_dropped if ai_note else 0,
        "plan": plan,
        "alternatives": [{"id": c["id"], "title": c["title"], "layer": c["layer"]}
                         for c, _ in card_hits if not chosen or c["id"] != chosen["id"]],
        "cited": [_chunk_view(c) for c in cited_chunks],
        "related": [_chunk_view(c) for c in chunks if c["id"] not in cited][:5],
        "personal_notes": [_chunk_view(c) for c in personal],
    }


def _chunk_view(c: dict) -> dict:
    return {k: c[k] for k in ("id", "doc_id", "title", "label", "loc", "text", "layer")}


def _offline_answer(plan: dict | None, chunks: list[dict]) -> str:
    if not plan:
        if chunks:
            return ("맞는 절차 카드를 찾지 못했습니다. 아래 관련 규정 조문을 확인하시고, "
                    "자주 하는 업무라면 '절차 카드' 화면에서 카드를 만들어 두세요.")
        return "등록된 규정·절차에서 관련 내용을 찾지 못했습니다. 다른 표현으로 다시 말씀해 주세요."
    st = plan["steps"]
    parts = [f"'{plan['card']['title']}' 절차로 안내합니다. 모두 {len(st)}단계입니다."]
    if plan["missing_bases"]:
        parts.append(f"기한을 계산하려면 {', '.join(plan['missing_bases'])}을(를) 입력해 주세요.")
    if plan["next_index"] is not None and st:
        s = st[plan["next_index"]]
        due = f" ({s['due_text']}까지, {s['dday']['label']})" if s["due"] else ""
        parts.append(f"지금 할 일은 {s['no']}단계 '{s['title']}'입니다{due}.")
    elif st:
        parts.append("모든 단계의 기한이 지났습니다. 늦은 단계는 담당 부서에 먼저 문의하세요.")
    forms = list(dict.fromkeys(f["name"] for s in st for f in s["forms"]))
    if forms:
        parts.append(f"필요 서식: {', '.join(forms)}.")
    return " ".join(parts)
