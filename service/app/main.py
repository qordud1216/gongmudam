"""서무비서 웹 서버. 실행: python -m app.main  (또는 run.bat)"""
from __future__ import annotations

import shutil
import copy
from contextlib import asynccontextmanager
import tempfile
import threading
import uuid
import webbrowser
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import assistant, config, deadlines, formfill, llm, parsers, seed, store, tracker, travel_api
from . import local_ai
from . import workspace
from . import leave
from . import adhoc, folders, folder_ai, folder_watch, change_inbox, folder_inputs
from . import knowledge, answer_tree, manual_knowledge
from . import education_intent, workflow_chat, task_intent
from . import guidance
from . import regulation_monitor,regulation_registry
from . import toolbox, folder_scan, calendar_api, education_calendar, calendar_agenda

ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def _lifespan(_app):
    travel_api.initialize()
    adhoc.initialize()
    toolbox.initialize()
    folders.initialize()
    folder_scan.initialize(recover=True)
    calendar_api.initialize()
    calendar_agenda.initialize()
    knowledge.initialize()
    folder_ai.initialize()
    folder_watch.initialize()
    store.conn()
    if store.is_empty():
        seed.load_seed()
    watcher=folder_watch.Worker().start()
    regulation_registry.initialize()
    regulation_worker=regulation_monitor.Worker().start()
    try:
        yield
    finally:
        watcher.stop()
        folder_scan.stop()
        regulation_worker.stop()


app = FastAPI(title="서무비서", version="1.0.0", lifespan=_lifespan)
app.include_router(travel_api.router)
app.include_router(local_ai.router)
app.include_router(workspace.router)
app.include_router(adhoc.router)
app.include_router(toolbox.router)
app.include_router(folders.router)
app.include_router(folder_inputs.router)
app.include_router(folder_scan.router)
app.include_router(calendar_api.router)
app.include_router(education_calendar.router)
app.include_router(calendar_agenda.router)
app.include_router(knowledge.router)
app.include_router(folder_ai.router)
app.include_router(folder_watch.router)
app.include_router(change_inbox.router)
app.include_router(regulation_monitor.router)


def _today(s: str | None) -> date:
    return deadlines.parse_iso(s) or date.today()


@app.exception_handler(parsers.ParseError)
async def _parse_err(_req, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(ValueError)
async def _value_err(_req, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


# ------------------------------------------------------------------ 상황 안내
@app.post("/api/ask")
def api_ask(body: dict = Body(...)) -> dict:
    query=str(body.get('query') or '').strip()
    if not query or len(query)>3000:raise HTTPException(422,'질문은 1~3000자로 입력하세요.')
    edit_result=workflow_chat.handle(query,body)
    if edit_result is not None:return edit_result
    if body.get('guidance') is True and not body.get('card_id') and not body.get('leave_type'):
        return guidance.respond(query,body,_today(body.get('today')))
    manual_reply=manual_knowledge.respond(query,body.get('knowledge_library_id') or None)
    if manual_reply is not None and not body.get('card_id') and not body.get('leave_type'):return manual_reply
    task_action = task_intent.action(query)
    def with_task_action(result: dict) -> dict:
        if task_action:
            result['task_action'] = task_action
        return result
    if task_intent.is_folder_start(query, task_action) and not body.get('knowledge_library_id') and not body.get('card_id') and not body.get('leave_type'):
        return with_task_action(dict(query=query,mode='folder_workflow',model=None,profile=None,
            summary='폴더를 고르고, 자료를 업무별로 정리해요.',
            answer='폴더 선택 → 문서 내용 확인 → 업무별 분류 검토 → 분석 결과 저장\n\n위의 ‘이 내용으로 업무자료 정리’를 누르면 입력한 업무 목적을 이어받아요. 정리할 폴더를 직접 고른 뒤 분류 제안을 확인하고 저장하세요.',
            notice='분류 제안은 담당자가 확인해 적용해요. 파일 원본은 그대로 보존해요.',
            plan=None,alternatives=[],cited=[],related=[],personal_notes=[]))
    if task_action and education_intent.is_start_request(query) and not body.get('card_id') and not body.get('leave_type'):
        return with_task_action(dict(query=query,mode='education_workflow',model=None,profile=None,
            summary='교육 희망자 취합을 함께 준비해요.',
            answer='안내 확인 → 희망자 모집 → 회신 취합 → 누락·중복 검토 → 명단·결과보고\n\n위의 ‘교육 취합 시작하기’를 누르면 입력한 내용을 이어받고, 교육명·일정·대상 부서를 확인해요. 단계마다 필요한 서식과 자료를 연결할 수 있어요.',
            notice='앱의 실무 진행 안내예요. 기관의 공식 절차·법적 근거는 등록한 자료로 별도 확인해요.',
            plan=None,alternatives=[],cited=[],related=[],personal_notes=[]))
    found=knowledge.retrieve(query,body.get('knowledge_library_id') or None,_today(body.get('today')))
    if (found['hits'] or body.get('knowledge_library_id') or found['requires_basis']) and not body.get('card_id') and not body.get('leave_type'):
        reply=knowledge.answer(query,found)
        reply['tree']=answer_tree.build(query,reply)
        summary=('상황을 조금 더 확인한 뒤 맞는 근거를 찾겠습니다.' if reply['mode']=='source_clarification' else
                 '등록 원문에서 확인한 내용입니다. 인용 번호에 해당하는 출처와 적용 조건을 함께 확인하세요.' if found['hits'] else
                 '등록한 자료에서 질문에 필요한 직접 근거를 확인하지 못했습니다.')
        return with_task_action(dict(query=query,mode=reply['mode'],model=reply['model'],profile=None,summary=summary,answer=reply['answer'],notice=reply['notice'],plan=None,alternatives=[],cited=[],related=[],personal_notes=[],knowledge=reply))
    # 이미 저장·선택한 합성 절차 카드는 보존하고, 새 질문은 휴가 분류부터 확인한다.
    leave_result=leave.guide(str(body.get("query") or ""),body.get("leave_type"),body.get("leave_context")) if not body.get("card_id") or body.get("leave_type") else None
    if leave_result is not None:
        leave_result['knowledge']=dict(evidence=[],experiences=found['experiences'],excluded=found['excluded'],scope='처리 경험은 공식 규정이 아닙니다.')
        return with_task_action(leave_result)
    result=assistant.ask(body.get("query", ""), today=_today(body.get("today")), layers=body.get("layers") or None,
                         card_id=body.get("card_id"), base_values=body.get("base_values"),
                         conditions=body.get("conditions"))
    result['knowledge']=dict(evidence=[],experiences=found['experiences'],excluded=found['excluded'],scope='처리 경험은 공식 규정이 아닙니다.')
    return with_task_action(result)


@app.post("/api/plan")
def api_plan(body: dict = Body(...)) -> dict:
    card = store.get_card(body.get("card_id", ""))
    if not card:
        raise HTTPException(404, "절차 카드가 없습니다.")
    bv = {k: d for k, v in (body.get("base_values") or {}).items() if (d := deadlines.parse_iso(v))}
    return assistant.build_plan(card, bv, _today(body.get("today")), body.get("conditions"))


# ------------------------------------------------------------------ 진행 중인 업무(홈)
@app.get("/api/home")
def api_home(today: str = "") -> dict:
    return tracker.overview(_today(today))


@app.post("/api/tracked")
def api_track(body: dict = Body(...)) -> dict:
    return tracker.add(body.get("card_id", ""), body.get("base_values"), body.get("label", ""), body.get("conditions"))


@app.put("/api/tracked/{item_id}")
def api_track_update(item_id: str, body: dict = Body(...)) -> dict:
    try:
        return tracker.update(item_id, done=body.get("done"), base_values=body.get("base_values"))
    except KeyError:
        raise HTTPException(404, "등록된 업무가 없습니다.")


@app.delete("/api/tracked/{item_id}")
def api_track_delete(item_id: str) -> dict:
    if not tracker.remove(item_id):
        raise HTTPException(404, "등록된 업무가 없습니다.")
    return {"ok": True}


# ------------------------------------------------------------------ 문서
@app.get("/api/documents")
def api_documents() -> list[dict]:
    return store.list_documents()


@app.get("/api/documents/{doc_id}")
def api_document(doc_id: str) -> dict:
    d = store.get_document(doc_id)
    if not d:
        raise HTTPException(404, "문서가 없습니다.")
    return d


def _stage(upload: UploadFile) -> Path:
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in parsers.SUPPORTED:
        raise parsers.ParseError(f"지원하지 않는 형식입니다: {ext or '확장자 없음'} (지원: {', '.join(sorted(parsers.SUPPORTED))})")
    tmp = Path(tempfile.gettempdir()) / f"seomu_{uuid.uuid4().hex}{ext}"
    with open(tmp, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return tmp


def _check(kind: str, layer: str) -> None:
    if kind not in store.KINDS:
        raise ValueError(f"종류는 {', '.join(store.KINDS)} 중 하나입니다.")
    if layer not in store.LAYERS:
        raise ValueError(f"적용 범위는 {', '.join(store.LAYERS)} 중 하나입니다.")


@app.post("/api/documents")
def api_add_document(file: UploadFile = File(...), title: str = Form(""), kind: str = Form("규정"),
                     layer: str = Form("기관"), note: str = Form("")) -> dict:
    _check(kind, layer)
    tmp = _stage(file)
    try:
        return store.add_document(tmp, title=title.strip() or Path(file.filename).stem, kind=kind, layer=layer,
                                  note=note, filename=file.filename)
    finally:
        tmp.unlink(missing_ok=True)


@app.put("/api/documents/{doc_id}")
def api_update_document(doc_id: str, body: dict = Body(...)) -> dict:
    d = store.get_document(doc_id)
    if not d:
        raise HTTPException(404, "문서가 없습니다.")
    kind, layer = body.get("kind", d["kind"]), body.get("layer", d["layer"])
    _check(kind, layer)
    return store.update_document_meta(doc_id, title=body.get("title", d["title"]), kind=kind, layer=layer,
                                      note=body.get("note", d["note"]))


@app.post("/api/documents/{doc_id}/file")
def api_replace_document(doc_id: str, file: UploadFile = File(...)) -> dict:
    """개정본으로 교체. 같은 ID를 유지하므로 절차 카드의 근거 연결이 이어지고, 바뀐 조문은 경고로 표시된다."""
    d = store.get_document(doc_id)
    if not d:
        raise HTTPException(404, "문서가 없습니다.")
    tmp = _stage(file)
    try:
        return store.add_document(tmp, title=d["title"], kind=d["kind"], layer=d["layer"], note=d["note"],
                                  filename=file.filename, doc_id=doc_id)
    finally:
        tmp.unlink(missing_ok=True)


@app.delete("/api/documents/{doc_id}")
def api_delete_document(doc_id: str) -> dict:
    if not store.delete_document(doc_id):
        raise HTTPException(404, "문서가 없습니다.")
    return {"ok": True}


@app.get("/api/documents/{doc_id}/download")
def api_download_document(doc_id: str):
    d = store.get_document(doc_id)
    if not d:
        raise HTTPException(404, "문서가 없습니다.")
    return FileResponse(store.document_path(d), filename=d["filename"])


@app.get("/api/chunks")
def api_chunks(q: str = "") -> list[dict]:
    """절차 카드 편집 시 근거 조문을 고르기 위한 검색."""
    if q.strip():
        return [dict(c, score=round(s, 2)) for c, s in assistant.search_chunks(q, k=15)]
    return store.all_chunks()[:50]


# ------------------------------------------------------------------ 절차 카드
@app.get("/api/cards")
def api_cards() -> list[dict]:
    return store.list_cards()


@app.get("/api/cards/{card_id}")
def api_card(card_id: str) -> dict:
    c = store.get_card(card_id)
    if not c:
        raise HTTPException(404, "절차 카드가 없습니다.")
    return c


@app.post("/api/cards")
def api_save_card(body: dict = Body(...)) -> dict:
    if body.get("layer", "기관") not in store.LAYERS:
        raise ValueError("적용 범위가 올바르지 않습니다.")
    for s in body.get("steps") or []:
        dl = s.get("deadline")
        if dl and dl.get("base") and dl["base"] not in (body.get("base_dates") or []):
            raise ValueError(f"단계 '{s.get('title')}'의 기준일 '{dl['base']}'이 카드 기준일 목록에 없습니다.")
    return store.save_card(body)


@app.delete("/api/cards/{card_id}")
def api_delete_card(card_id: str) -> dict:
    if not store.delete_card(card_id):
        raise HTTPException(404, "절차 카드가 없습니다.")
    return {"ok": True}


# ------------------------------------------------------------------ 서식
@app.get("/api/forms")
def api_forms() -> list[dict]:
    return store.list_forms()


@app.post("/api/forms")
def api_save_form(body: dict = Body(...)) -> dict:
    if not (body.get("name") or "").strip():
        raise ValueError("서식 이름을 입력하세요.")
    keys = [f.get("key") for f in body.get("fields") or []]
    if any(not k for k in keys) or len(set(keys)) != len(keys):
        raise ValueError("칸 이름은 비워 둘 수 없고 서로 달라야 합니다.")
    return store.save_form(body)


@app.delete("/api/forms/{form_id}")
def api_delete_form(form_id: str) -> dict:
    if not store.delete_form(form_id):
        raise HTTPException(404, "서식이 없습니다.")
    return {"ok": True}


@app.post("/api/forms/{form_id}/prefill")
def api_prefill(form_id: str, body: dict = Body(...)) -> dict:
    f = store.get_form(form_id)
    if not f:
        raise HTTPException(404, "서식이 없습니다.")
    return formfill.prefill(f, query=body.get("query", ""), base_values=body.get("base_values"),
                            today=_today(body.get("today")), use_llm=body.get("use_llm", True))


@app.post("/api/forms/{form_id}/export")
def api_export(form_id: str, body: dict = Body(...)):
    f = store.get_form(form_id)
    if not f:
        raise HTTPException(404, "서식이 없습니다.")
    path = formfill.export_docx(f, body.get("values") or {}, card_title=body.get("card_title", ""))
    return FileResponse(path, filename=path.name,
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# ------------------------------------------------------------------ 설정
@app.get("/api/settings")
def api_settings() -> dict:
    cfg = config.load()
    return {"llm": config.public_llm_view(cfg), "profile": store.get_setting("profile", {}),
            "layers": store.LAYERS, "kinds": store.KINDS, "today": date.today().isoformat()}


@app.put("/api/settings/profile")
def api_profile(body: dict = Body(...)) -> dict:
    store.set_setting("profile", {k: str(v) for k, v in body.items()})
    return {"ok": True}


@app.put("/api/settings/llm")
def api_llm(body: dict = Body(...)) -> dict:
    """active 프로필 전환과 프로필 값 수정. api_key 를 빈 값으로 보내면 기존 키를 유지한다."""
    def change(cfg):
        previous_selection = copy.deepcopy(config.active_profile(cfg))
        llm_cfg = cfg.setdefault("llm", {})
        profiles = llm_cfg.setdefault("profiles", {})
        name = body.get("profile")
        if body.get("values") and name:
            cur = profiles.setdefault(name, {"provider": "openai_compatible"})
            for k, v in body["values"].items():
                if k == "api_key" and not v:
                    continue
                if k in ("temperature",):
                    v = float(v)
                if k in ("max_tokens", "timeout"):
                    v = int(v)
                cur[k] = v
        if body.get("active"):
            if body["active"] not in profiles:
                raise ValueError("없는 프로필입니다.")
            llm_cfg["active"] = body["active"]
        if config.active_profile(cfg) != previous_selection:
            llm_cfg["_selection_revision"] = int(llm_cfg.get("_selection_revision", 0)) + 1
        return config.public_llm_view(cfg)
    return config.update(change)


@app.post("/api/settings/llm/test")
def api_llm_test(body: dict = Body(default={})) -> dict:
    cfg = config.load()
    name = body.get("profile") or cfg["llm"].get("active")
    prof = dict(cfg["llm"]["profiles"].get(name) or {})
    provider = llm.get_provider(prof)
    if not provider.available:
        return {"ok": True, "message": "오프라인 모드: 모델을 호출하지 않고 규칙 기반으로 동작합니다."}
    try:
        out = provider.chat([{"role": "user", "content": "'연결 성공' 네 글자만 답하세요."}], max_tokens=20)
        # 모델이 쓴 문장은 화면에 옮기지 않는다. 응답을 받았다는 사실만 알린다.
        return {"ok": True, "message": f"{prof.get('model')} 연결 성공: 응답 {len(out)}자를 받았습니다."}
    except llm.LLMError as e:
        return {"ok": False, "message": f"연결 시험 실패(오류 종류: {e.kind}). 자세한 내용은 서버 창 로그를 확인하세요."}


@app.post("/api/settings/reset-sample")
def api_reset() -> dict:
    return seed.load_seed(reset=True)


@app.get("/api/holidays")
def api_holidays() -> dict[str, Any]:
    return deadlines.holidays()


@app.get('/',include_in_schema=False)
def workspace_home():
    return RedirectResponse('/start.html',status_code=307)


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")


def run() -> None:
    import uvicorn
    cfg = config.load().get("server", {})
    host, port = cfg.get("host", "127.0.0.1"), int(cfg.get("port", 8765))
    print(f"서무비서 실행 중: http://{host}:{port}  (끄려면 이 창에서 Ctrl+C)")
    if cfg.get("open_browser", True):
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    run()
