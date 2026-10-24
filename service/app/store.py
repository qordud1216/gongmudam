"""SQLite 저장소. 규정·지침·서식 문서, 조문 단위 청크, 업무별 절차 카드, 서식 정의를 보관한다.

- 등록한 원본 파일은 data/library/ 에 사본으로 보관한다 (사용자가 고른 원본은 읽기만 함).
- 문서마다 SHA-256 을 기록해 같은 파일의 중복 등록과 변경 여부를 판단한다.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from . import parsers

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LIBRARY = DATA / "library"
DB_PATH = DATA / "seomu.db"

LAYERS = ("공통", "기관", "개인")
KINDS = ("규정", "지침", "서식", "매뉴얼", "메모")

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL, layer TEXT NOT NULL,
  filename TEXT NOT NULL, stored_name TEXT NOT NULL, sha256 TEXT NOT NULL,
  note TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL, label TEXT NOT NULL, loc TEXT NOT NULL, text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(doc_id);
CREATE TABLE IF NOT EXISTS cards (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL, layer TEXT NOT NULL,
  keywords TEXT DEFAULT '', summary TEXT DEFAULT '', base_dates TEXT DEFAULT '[]',
  steps TEXT DEFAULT '[]', status TEXT DEFAULT '초안', notes TEXT DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, reviewed_at TEXT
);
CREATE TABLE IF NOT EXISTS forms (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, doc_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
  fields TEXT DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            DATA.mkdir(parents=True, exist_ok=True)
            LIBRARY.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA foreign_keys = ON")
            _conn.executescript(SCHEMA)
        return _conn


def _rows(sql: str, args: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def _exec(sql: str, args: tuple = ()) -> None:
    with _lock:
        c = conn()
        c.execute(sql, args)
        c.commit()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


# ------------------------------------------------------------------ 조문 단위 묶기
_ARTICLE = re.compile(r"^\s*(제\s*\d+\s*조(?:의\s*\d+)?)\s*(\([^)]*\))?")
_HEADING = re.compile(r"^\s*(\d+\.\s|[가-하]\.\s|[□■◆▶]\s?)")


def group_units(units: list[dict], tabular: bool = False) -> list[dict]:
    """파서가 준 문단 목록을 조문(제N조) 또는 소제목 단위로 묶는다.
    label 은 근거 표시에 쓰는 이름(예: '제7조(여비의 정산)'), loc 은 원문 위치다.
    표(엑셀·CSV)는 행 하나를 근거 하나로 본다."""
    if tabular:
        return [{"label": f"{u['loc']} {u['text'].split(' / ')[0]}"[:60], "loc": u["loc"], "text": u["text"]}
                for u in units]
    has_articles = any(_ARTICLE.match(u["text"]) for u in units)
    groups: list[dict] = []
    cur: dict | None = None
    for u in units:
        t = u["text"].strip()
        m = _ARTICLE.match(t)
        start = bool(m) if has_articles else (bool(_HEADING.match(t)) or cur is None)
        if start or cur is None:
            if m:
                label = re.sub(r"\s+", "", m.group(1)) + (m.group(2) or "")
            else:
                label = t[:30] + ("…" if len(t) > 30 else "")
            cur = {"label": label, "loc": u["loc"], "texts": [t]}
            groups.append(cur)
        else:
            cur["texts"].append(t)
            if len(" ".join(cur["texts"])) > 1500 and not has_articles:
                cur = None
    out = []
    for g in groups:
        out.append({"label": g["label"], "loc": g["loc"], "text": "\n".join(g["texts"])})
    return out


# ------------------------------------------------------------------ 문서
def list_documents() -> list[dict]:
    docs = _rows("SELECT * FROM documents ORDER BY CASE layer WHEN '공통' THEN 0 WHEN '기관' THEN 1 ELSE 2 END, title")
    counts = {r["doc_id"]: r["n"] for r in _rows("SELECT doc_id, COUNT(*) n FROM chunks GROUP BY doc_id")}
    for d in docs:
        d["chunk_count"] = counts.get(d["id"], 0)
    return docs


def get_document(doc_id: str) -> dict | None:
    r = _rows("SELECT * FROM documents WHERE id=?", (doc_id,))
    if not r:
        return None
    d = r[0]
    d["chunks"] = _rows("SELECT id, seq, label, loc, text FROM chunks WHERE doc_id=? ORDER BY seq", (doc_id,))
    return d


def find_document_by_sha(sha: str) -> dict | None:
    r = _rows("SELECT * FROM documents WHERE sha256=?", (sha,))
    return r[0] if r else None


def add_document(src: Path, *, title: str, kind: str, layer: str, filename: str | None = None,
                 note: str = "", doc_id: str | None = None, insert: bool = False) -> dict:
    """insert=True 이면 doc_id 를 새 문서의 고정 ID로 쓴다(모의데이터용). 아니면 doc_id 문서를 새 파일로 교체한다."""
    """src 파일을 읽기만 해서 라이브러리에 사본을 두고 조문 단위로 색인한다."""
    filename = filename or src.name
    ext = Path(filename).suffix.lower()
    if ext not in parsers.SUPPORTED:
        raise parsers.ParseError(f"지원하지 않는 형식입니다: {ext}")
    sha = sha256_of(src)
    dup = find_document_by_sha(sha)
    if dup and (insert or dup["id"] != doc_id):
        raise ValueError(f"이미 등록된 파일입니다: {dup['title']}")
    new_id = doc_id or uuid.uuid4().hex[:12]
    stored = f"{new_id}{ext}"
    staged = LIBRARY / (f"_staging_{uuid.uuid4().hex[:8]}" + ext)
    LIBRARY.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, staged)
    try:
        units = parsers.parse_file(staged)
    except Exception:
        staged.unlink(missing_ok=True)
        raise
    if not units:
        staged.unlink(missing_ok=True)
        raise parsers.ParseError("문서에서 글자를 읽지 못했습니다 (그림으로 된 문서이거나 빈 문서).")
    groups = group_units(units, tabular=ext in (".xlsx", ".xlsm", ".csv")) if kind != "서식" else [
        {"label": f"{i}번째 문단", "loc": u["loc"], "text": u["text"]} for i, u in enumerate(units, 1)]
    with _lock:
        c = conn()
        ts = now()
        if doc_id and not insert:
            old = _rows("SELECT stored_name FROM documents WHERE id=?", (doc_id,))
            c.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            c.execute("UPDATE documents SET title=?, kind=?, layer=?, filename=?, stored_name=?, sha256=?, note=?, updated_at=? WHERE id=?",
                      (title, kind, layer, filename, stored, sha, note, ts, doc_id))
            if old and old[0]["stored_name"] != stored:
                (LIBRARY / old[0]["stored_name"]).unlink(missing_ok=True)
        else:
            c.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (new_id, title, kind, layer, filename, stored, sha, note, ts, ts))
        for i, g in enumerate(groups):
            c.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?)",
                      (f"{new_id}-{i + 1}", new_id, i + 1, g["label"], g["loc"], g["text"]))
        c.commit()
    staged.replace(LIBRARY / stored)
    return get_document(new_id)


def update_document_meta(doc_id: str, *, title: str, kind: str, layer: str, note: str) -> dict | None:
    _exec("UPDATE documents SET title=?, kind=?, layer=?, note=?, updated_at=? WHERE id=?",
          (title, kind, layer, note, now(), doc_id))
    return get_document(doc_id)


def delete_document(doc_id: str) -> bool:
    r = _rows("SELECT stored_name FROM documents WHERE id=?", (doc_id,))
    if not r:
        return False
    _exec("DELETE FROM documents WHERE id=?", (doc_id,))
    (LIBRARY / r[0]["stored_name"]).unlink(missing_ok=True)
    return True


def document_path(doc: dict) -> Path:
    return LIBRARY / doc["stored_name"]


def all_chunks(layers: list[str] | None = None) -> list[dict]:
    sql = ("SELECT c.id, c.doc_id, c.label, c.loc, c.text, d.title, d.kind, d.layer FROM chunks c "
           "JOIN documents d ON d.id=c.doc_id")
    rows = _rows(sql)
    if layers:
        rows = [r for r in rows if r["layer"] in layers]
    return rows


def resolve_basis(doc_id: str, label: str) -> dict | None:
    """근거(문서 ID + 조문 이름)를 현재 등록된 청크로 찾는다. 개정으로 사라졌으면 None."""
    rows = _rows("SELECT c.id, c.doc_id, c.label, c.loc, c.text, d.title, d.layer, d.updated_at FROM chunks c "
                 "JOIN documents d ON d.id=c.doc_id WHERE c.doc_id=?", (doc_id,))
    norm = lambda s: re.sub(r"\s+", "", s or "")  # noqa: E731
    for r in rows:
        if norm(r["label"]) == norm(label):
            return r
    # '제7조' 만 적은 경우 조 번호로 맞춘다
    m = re.match(r"제\s*\d+\s*조(?:의\s*\d+)?", label or "")
    if m:
        for r in rows:
            if norm(r["label"]).startswith(norm(m.group(0))):
                return r
    return None


# ------------------------------------------------------------------ 절차 카드
_CARD_JSON = ("base_dates", "steps")


def _card_out(r: dict) -> dict:
    for k in _CARD_JSON:
        r[k] = json.loads(r[k] or "[]")
    return r


def list_cards() -> list[dict]:
    return [_card_out(r) for r in _rows(
        "SELECT * FROM cards ORDER BY category, CASE layer WHEN '개인' THEN 0 WHEN '기관' THEN 1 ELSE 2 END, title")]


def get_card(card_id: str) -> dict | None:
    r = _rows("SELECT * FROM cards WHERE id=?", (card_id,))
    return _card_out(r[0]) if r else None


def save_card(card: dict) -> dict:
    ts = now()
    cid = card.get("id") or uuid.uuid4().hex[:12]
    exists = bool(_rows("SELECT 1 FROM cards WHERE id=?", (cid,)))
    status = card.get("status") or "초안"
    reviewed = ts if status == "확정" else card.get("reviewed_at")
    vals = (card.get("title", "").strip() or "제목 없음", card.get("category", "기타"),
            card.get("layer", "기관"), card.get("keywords", ""), card.get("summary", ""),
            json.dumps(card.get("base_dates") or [], ensure_ascii=False),
            json.dumps(card.get("steps") or [], ensure_ascii=False), status, card.get("notes", ""))
    if exists:
        _exec("UPDATE cards SET title=?, category=?, layer=?, keywords=?, summary=?, base_dates=?, steps=?, "
              "status=?, notes=?, updated_at=?, reviewed_at=? WHERE id=?", vals + (ts, reviewed, cid))
    else:
        _exec("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (cid,) + vals + (card.get("created_at") or ts, ts, reviewed))
    return get_card(cid)


def delete_card(card_id: str) -> bool:
    if not _rows("SELECT 1 FROM cards WHERE id=?", (card_id,)):
        return False
    _exec("DELETE FROM cards WHERE id=?", (card_id,))
    return True


# ------------------------------------------------------------------ 서식
def list_forms() -> list[dict]:
    rows = _rows("SELECT f.*, d.title AS doc_title, d.filename AS doc_filename FROM forms f "
                 "LEFT JOIN documents d ON d.id=f.doc_id ORDER BY f.name")
    for r in rows:
        r["fields"] = json.loads(r["fields"] or "[]")
    return rows


def get_form(form_id: str) -> dict | None:
    for f in list_forms():
        if f["id"] == form_id:
            return f
    return None


def save_form(form: dict) -> dict:
    ts = now()
    fid = form.get("id") or uuid.uuid4().hex[:12]
    fields = json.dumps(form.get("fields") or [], ensure_ascii=False)
    if _rows("SELECT 1 FROM forms WHERE id=?", (fid,)):
        _exec("UPDATE forms SET name=?, doc_id=?, fields=?, updated_at=? WHERE id=?",
              (form["name"], form.get("doc_id"), fields, ts, fid))
    else:
        _exec("INSERT INTO forms VALUES (?,?,?,?,?,?)", (fid, form["name"], form.get("doc_id"), fields, ts, ts))
    return get_form(fid)


def delete_form(form_id: str) -> bool:
    if not _rows("SELECT 1 FROM forms WHERE id=?", (form_id,)):
        return False
    _exec("DELETE FROM forms WHERE id=?", (form_id,))
    return True


# ------------------------------------------------------------------ 설정(사용자 정보)
def get_setting(key: str, default: Any = None) -> Any:
    r = _rows("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(r[0]["value"]) if r else default


def set_setting(key: str, value: Any) -> None:
    _exec("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
          (key, json.dumps(value, ensure_ascii=False)))


def is_empty() -> bool:
    return not _rows("SELECT 1 FROM documents LIMIT 1") and not _rows("SELECT 1 FROM cards LIMIT 1")


def reset_all() -> None:
    """모든 등록 자료를 지운다(모의데이터 다시 불러오기용). 입력 원본은 건드리지 않는다."""
    with _lock:
        c = conn()
        for t in ("chunks", "forms", "cards", "documents"):
            c.execute(f"DELETE FROM {t}")
        c.execute("DELETE FROM settings WHERE key='tracked'")
        c.commit()
    for p in LIBRARY.glob("*"):
        if p.is_file():
            p.unlink()
