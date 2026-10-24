"""Narrow deterministic detection for education attendee collection requests."""
import re


_EDUCATION = re.compile(r"(?:교육|연수|워크숍|워크샵|교육생|수강생)")
_COLLECTION = re.compile(r"(?:참석자|참가자|수강생|교육생|희망자|신청자|대상자|명단|인원)")
_ACTION = re.compile(r"(?:모집|취합|수합|조사|신청(?:을)?(?:받|접수)|파악|명단.{0,8}(?:작성|정리|취합|만들)|참석.{0,8}(?:자|인원).{0,8}(?:취합|모집|조사))")
_NEGATIVE = re.compile(r"(?:출장|여비|교통비|숙박비|정산|환급|보상|휴가|휴무|연가|병가)")
_LEGAL_QUESTION = re.compile(r"(?:법령|규정|지침|근거|조문|법적|의무|보관기간|보존기간|개인정보|기준|자격|선발|선정)")


def is_education_collection_request(query: str) -> bool:
    """Return true only for explicit education-related participant collection."""
    text = str(query or "").strip()
    if not text or _NEGATIVE.search(text):
        return False
    return bool(_EDUCATION.search(text) and _COLLECTION.search(text) and _ACTION.search(text))


def is_start_request(query: str) -> bool:
    return is_education_collection_request(query) and not _LEGAL_QUESTION.search(query)
