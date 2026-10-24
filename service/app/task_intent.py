"""Explicit links from an answer to an existing work screen; never creates work."""
import re

from . import education_intent


def action(query: str) -> dict | None:
    text = str(query or '').strip()
    if education_intent.is_education_collection_request(text):
        return {'kind': 'education_collection', 'label': '이 업무 시작하기'}
    if (re.search(r'폴더|자료함|파일', text)
            and re.search(r'정리|분류|묶[어기음]|연결|분석', text)
            and not re.search(r'(?:정리|분류|연결|분석).{0,6}(?:하지\s*마|말고|제외)', text)
            and not re.search(r'출장.{0,12}정산|여비.{0,12}계산', text)):
        return {'kind': 'folder_organize', 'label': '이 내용으로 업무자료 정리'}
    if re.search(r'출장|여비', text) and re.search(r'정산|계산|청구|증빙|영수증', text):
        return {'kind': 'travel_settlement', 'label': '이 내용으로 출장정산 준비'}
    return None


def is_folder_start(query: str, task: dict | None) -> bool:
    # Only an explicit start command can bypass retrieval. A question mentioning
    # file organization may concern retention, disposal, privacy, or other law.
    return bool(task and task['kind'] == 'folder_organize'
                and re.search(r'(?:정리|분류|연결|분석)(?:하(?:고\s*싶|려|겠|자)|해\s*(?:줘|주|줄|보)|해요|해\s*$)|(?:정리|분류|연결|분석).{0,8}부탁',query)
                and not re.search(r'법령|규정|지침|근거|기준|법적|의무|조문|보존기간|보관기간|개인정보|저작권|보안|가능한가|해도\s*되|폐기|절차|설명|제\s*\d+\s*[조항]|[가-힣]{2,}법(?:\s|[은는이가을를의에]|$)', query))
