"""모의데이터 불러오기. sample_data/seed.json 에 적힌 문서를 등록하고 절차 카드·서식 정의를 넣는다.
sample_data 폴더의 파일은 읽기만 한다(사본이 data/library 로 들어간다)."""
from __future__ import annotations

import json
from pathlib import Path

from . import store

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample_data"


def load_seed(reset: bool = False) -> dict:
    if reset:
        store.reset_all()
    seed = json.loads((SAMPLE / "seed.json").read_text(encoding="utf-8"))
    docs = 0
    for d in seed["documents"]:
        if store.get_document(d["id"]):
            continue
        _add(d)
        docs += 1
    for f in seed["forms"]:
        store.save_form(f)
    for c in seed["cards"]:
        store.save_card(c)
    if not store.get_setting("profile"):
        store.set_setting("profile", seed.get("profile", {}))
    return {"documents": docs, "forms": len(seed["forms"]), "cards": len(seed["cards"])}


def _add(d: dict) -> None:
    """고정 ID로 새 문서를 등록한다(절차 카드의 근거가 이 ID를 가리킨다)."""
    src = SAMPLE / d["path"]
    store.add_document(src, title=d["title"], kind=d["kind"], layer=d["layer"], note=d.get("note", ""),
                       filename=src.name, doc_id=d["id"], insert=True)
