"""진행 중인 업무: 상황 안내 결과(절차 카드 + 기준일)를 홈 화면에 등록해 두고 다음 할 일·기한을 모아 본다.
등록 정보는 settings 표의 'tracked' 값(목록)에 저장한다. 기한은 매번 build_plan 으로 다시 계산한다."""
from __future__ import annotations

import uuid
from datetime import date

from . import assistant, deadlines, store

KEY = "tracked"


def _items() -> list[dict]:
    return store.get_setting(KEY, []) or []


def _save(items: list[dict]) -> None:
    store.set_setting(KEY, items)


def add(card_id: str, base_values: dict[str, str] | None, label: str = "", conditions: list[str] | None = None) -> dict:
    card = store.get_card(card_id)
    if not card:
        raise ValueError("절차 카드가 없습니다.")
    bv = {k: v for k, v in (base_values or {}).items() if deadlines.parse_iso(v)}
    item = {"id": uuid.uuid4().hex[:12], "card_id": card_id, "label": (label or "").strip()[:80],
            "base_values": bv, "conditions": [str(x) for x in conditions or []], "done": [], "created_at": store.now()}
    _save(_items() + [item])
    return item


def update(item_id: str, *, done: list[int] | None = None, base_values: dict[str, str] | None = None) -> dict:
    items = _items()
    for it in items:
        if it["id"] == item_id:
            if done is not None:
                it["done"] = sorted({int(x) for x in done})
            if base_values is not None:
                it["base_values"] = {k: v for k, v in base_values.items() if deadlines.parse_iso(v)}
            _save(items)
            return it
    raise KeyError(item_id)


def remove(item_id: str) -> bool:
    items = _items()
    rest = [it for it in items if it["id"] != item_id]
    _save(rest)
    return len(rest) != len(items)


def overview(today: date) -> dict:
    """홈 화면용: 등록 업무별 다음 할 일과, 남은 단계 전체를 기한순으로 모은 목록."""
    tasks, upcoming = [], []
    for it in _items():
        card = store.get_card(it["card_id"])
        if not card:
            tasks.append({"id": it["id"], "label": it["label"], "missing": True, "title": "(삭제된 절차 카드)"})
            continue
        bv = {k: d for k, v in it["base_values"].items() if (d := deadlines.parse_iso(v))}
        plan = assistant.build_plan(card, bv, today, it.get("conditions"))
        done = set(it.get("done") or [])
        steps = [dict(s, done=(s["no"] - 1) in done) for s in plan["steps"]]
        left = [s for s in steps if not s["done"]]
        nxt = left[0] if left else None
        tasks.append({"id": it["id"], "label": it["label"], "card_id": card["id"], "title": card["title"],
                      "layer": card["layer"], "base_values": plan["base_values"], "missing_bases": plan["missing_bases"],
                      "warnings": plan["warnings"], "steps": steps, "next": nxt,
                      "progress": f"{len(steps) - len(left)}/{len(steps)}"})
        for s in left:
            if s["due"]:
                upcoming.append({"task_id": it["id"], "task": card["title"], "no": s["no"],
                                 "title": s["title"], "due": s["due"], "due_text": s["due_text"], "dday": s["dday"]})
    upcoming.sort(key=lambda x: x["due"])
    return {"today": today.isoformat(), "today_text": deadlines.fmt(today), "tasks": tasks, "upcoming": upcoming}
