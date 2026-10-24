"""휴가·휴무 종류와 확인사항 안내. 사용 권한·일수·기한을 판정하지 않는다.

일반 서무의 합성 연가 카드와 분리한 /api/ask 사전 분기이다.
질문과 종류가 모호하면 선택을 요청하고 실제 적용 규정은 신분별로 확인한다.
"""
from __future__ import annotations

import re

CHECKED = "2026-10-19"
MPM = "https://www.mpm.go.kr/mpm/info/infoService/BizService01/"
NATIONAL = "https://law.go.kr/lsLinkCommonInfo.do?lsJoLnkSeq=1017952009"
LOCAL = "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=290493&efYd=20261002"
TYPES = [
    {"id":"annual", "title":"연가", "group":"휴가", "description":"개인 일정과 휴식에 사용하는 휴가",
     "keywords":["연가","연차","반차","저축연가"], "questions":["사용하려는 날짜·시간과 잔여 연가를 확인하세요.","당겨쓰기·저축연가 사용 여부와 기관 신청·승인 절차를 확인하세요."],
     "documents":["기관 복무시스템의 연가 잔액·신청 내역"], "basis":"국가공무원 복무규정 제14조~제17조 · 인사혁신처 휴가제도 안내"},
    {"id":"sick", "title":"병가", "group":"휴가", "description":"질병·부상 등으로 근무가 어려울 때 검토",
     "keywords":["병가"], "questions":["본인 질병·부상인지, 공무상 사유인지 구분하세요.","사용 예정 기간·누적 병가와 진단서 등 제출 요건을 확인하세요. 병명·진단서 원문은 이 대화에 입력할 필요가 없습니다."],
     "documents":["사용 기간·누계 확인 내역","해당 시 기관이 요구하는 진단서 등 증빙"], "basis":"국가공무원 복무규정 제18조 · 인사혁신처 휴가제도 안내"},
    {"id":"official", "title":"공가", "group":"휴가", "description":"법령상 의무 이행·정해진 공적 사유를 확인",
     "keywords":["공가"], "questions":["검진·헌혈·예비군 등 구체적 사유가 규정의 공가 사유에 해당하는지 확인하세요.","필요한 날짜·시간과 참석·이행 증빙, 기관 처리 절차를 확인하세요. 모든 검진이나 시험이 자동 공가인 것은 아닙니다."],
     "documents":["해당 사유의 통지·안내 자료","기관이 요구하는 참석·이행 확인 자료"], "basis":"국가공무원 복무규정 제19조 · 인사혁신처 휴가제도 안내"},
    {"id":"special", "title":"특별휴가", "group":"휴가", "description":"경조사·출산·가족돌봄 등 세부 사유별 확인",
     "keywords":["특별휴가","특가","경조사","결혼휴가","출산휴가","가족돌봄","육아시간","모성보호","난임","재해구호","포상휴가","장기재직"],
     "questions":["경조사·출산·돌봄 등 세부 사유를 먼저 선택하세요.","대상자와의 관계·발생일·사용 기간, 유급·무급·분할사용·중복사용 조건을 해당 규정에서 확인하세요."],
     "documents":["세부 사유에 따라 기관이 요구하는 증빙","사용·분할·누계 내역"], "basis":"국가공무원 복무규정 제20조 · 인사혁신처 휴가제도 안내"},
    {"id":"substitute", "title":"대체휴무", "group":"휴무", "description":"시간외·공휴일 등 근무 후 휴무 부여 조건 확인",
     "keywords":["대체휴무","대체휴가"], "questions":["근무명령·실제 근무일·근무시간과 정상 근무일·비번일을 구분하세요.","기관의 휴무 부여·사용 시기 기준과 수당 등 중복 처리 제한을 확인하세요. 주말에 근무했다는 사정만으로 일수를 확정하지 않습니다."],
     "documents":["근무명령·실제 근무 기록","해당 근무표·휴무 지정 및 수당 처리 내역"], "basis":"국가공무원 복무규정 제11조제2항·제5항"},
    {"id":"conversion", "title":"시간외근무 연가 전환", "group":"전환 제도", "description":"수당 대신 연가로 전환하는 제도 · 보상휴가 용어 확인",
     "keywords":["보상휴가","연가전환","수당대신연가","수당대신휴가"], "questions":["기관에서 말하는 보상휴가가 공무원의 시간외근무 연가 전환인지, 공무직 등 다른 신분의 제도인지 확인하세요.","인정 근무시간·수당 지급 대상·전환 신청과 승인·이미 받은 보상을 확인하세요. 대체휴무와 같은 제도로 처리하지 않습니다."],
     "documents":["인정 시간외근무·수당 지급 대상 기록","기관의 전환 신청·승인 내역"], "basis":"국가공무원 복무규정 제11조제4항·제5항"},
]
SPECIAL = ["경조사", "출산·배우자 출산", "가족돌봄", "육아시간·모성보호", "난임치료·임신검진", "재해구호", "포상·장기재직", "그 밖의 특별휴가"]
SPECIAL_QUESTIONS = {
    "경조사":"결혼·입양·사망 등 경조사 구분, 대상자와의 관계 및 발생일을 확인하세요.",
    "출산·배우자 출산":"본인 출산과 배우자 출산을 구분하고, 예정·실제 출산일 및 해당하는 추가 조건을 확인하세요.",
    "가족돌봄":"돌봄 대상과의 관계, 돌봄 사유·기간, 사용 누계와 유급·무급 구분을 확인하세요.",
    "육아시간·모성보호":"일 단위 휴가와 시간 단위 제도를 구분하고, 대상 요건과 일일 근무시간·누적 사용을 확인하세요.",
    "난임치료·임신검진":"본인·배우자 및 치료·검진·동행 사유를 구분하고, 일정과 기관의 증빙 요건을 확인하세요.",
    "재해구호":"재난 피해 복구·자원봉사 등 사유, 활동 장소·기간과 기관 승인 요건을 확인하세요.",
    "포상·장기재직":"포상 결정·재직기간 등 부여 요건과 소속 기관의 근거·부여 내역을 확인하세요.",
    "그 밖의 특별휴가":"기관에서 사용하는 명칭과 해당 규정·조례의 조항, 발생 사유를 먼저 확인하세요.",
}
PERSONNEL = {"unknown":"선택 필요", "national":"국가공무원", "local":"지방공무원", "fire":"소방공무원", "other":"공무직·교원·기타"}
WORK = {"unknown":"선택 필요", "regular":"일반근무", "shift":"교대근무", "field":"현업근무"}


def detect(query: str) -> tuple[bool, list[str]]:
    flat=re.sub(r"\s+", "", query)
    hits=[t["id"] for t in TYPES if any(w in flat for w in t["keywords"])]
    # '연가 전환'의 '연가'는 별도 연가 신청 의도가 아니다.
    if 'conversion' in hits and 'annual' in hits: hits.remove('annual')
    # 가족의 질병을 본인의 병가로 단정하지 않고 특별휴가 후보로 둔다.
    clues={"special":["아이돌봄","자녀돌봄","아이가아파","아이병원","부모님간병","배우자출산","본인결혼"],
           "official":["헌혈","예비군","병역판정","국가건강검진"],
           "sick":["제가아파","제가다쳐","본인이아파","수술후휴가"],
           "substitute":["주말근무후쉬","휴일근무후쉬","주말에근무해서쉬"]}
    for kind,words in clues.items():
        if any(w in flat for w in words) and kind not in hits: hits.append(kind)
    relevant=bool(hits or any(w in flat for w in ["휴가","휴무","복무종류","쉬려고","쉬고싶","쉬어도"]))
    if not hits and any(w in flat for w in ["여비","정산","명절휴가비"]): relevant=False
    return relevant,hits


def guide(query: str, leave_type=None, context=None) -> dict | None:
    if leave_type is not None and (not isinstance(leave_type,str) or leave_type not in {t['id'] for t in TYPES}):
        raise ValueError("등록된 휴가·휴무 종류를 선택하세요.")
    relevant,hits=detect(query)
    if not relevant and leave_type is None: return None
    if len(query)>4000: raise ValueError("휴가 질문은 4,000자 이내로 입력하세요.")
    # '종류·차이' 및 여러 사유는 한 종류를 임의로 확정하지 않는다.
    overview=any(w in query for w in ["차이","비교","어떤 휴가"]) or ('종류' in query and len(hits)!=1)
    selected=leave_type or (hits[0] if len(hits)==1 and not overview else None)
    ctx=context if isinstance(context,dict) else {}
    personnel=ctx.get('personnel','unknown');work=ctx.get('work_pattern','unknown');subtype=ctx.get('subtype','')
    if not all(isinstance(v,str) for v in [personnel,work,subtype]) or personnel not in PERSONNEL or work not in WORK or (subtype and subtype not in SPECIAL):
        raise ValueError("신분·근무형태·특별휴가 사유를 목록에서 선택하세요.")
    selected_type=next((t for t in TYPES if t['id']==selected),None)
    missing=[]
    if not selected: missing.append("휴가·휴무 종류")
    if personnel=='unknown': missing.append("적용 신분")
    if work=='unknown': missing.append("근무형태")
    if selected=='special' and not subtype: missing.append("특별휴가 세부 사유")
    if personnel=='national': scope="국가공무원 기준의 확인 항목입니다. 소속 기관 지침과 사용일에 시행 중인 규정을 추가로 대조하세요."
    elif personnel=='local': scope="지방공무원 복무규정과 해당 지방자치단체의 복무 조례·지침을 추가로 확인해야 합니다. 아래 국가공무원 자료는 비교 참고자료이며 적용 근거로 확정하지 않습니다."
    elif personnel=='fire': scope="소방공무원에게 적용되는 복무 기준과 교대·현업 근무표를 별도로 확인해야 합니다. 아래 국가공무원 자료만으로 휴가·휴무 사용을 확정하지 않습니다."
    elif personnel=='other': scope="공무직·교원·기타 신분에는 해당 법령·취업규칙·단체협약 등을 먼저 확인하세요. 아래 공무원 규정을 자동 적용하지 않습니다."
    else: scope="국가·지방·소방·기타 신분을 먼저 확인하세요. 화면의 사용자 소속 이름만으로 적용 규정을 추정하지 않습니다."
    summary=(f"'{selected_type['title']}'의 확인 항목을 안내합니다." if selected_type else "휴가·휴무를 연가 하나로 정하지 않고, 사유에 맞는 종류부터 확인합니다.")
    sources=[{"title":"인사혁신처 공무원 휴가제도", "url":MPM, "scope":"국가공무원 참고자료"}]
    if selected in ['substitute','conversion']:
        sources=[{"title":selected_type['basis'],"url":NATIONAL,"scope":"국가공무원 · 시행 2026-10-02"}]
    if personnel=='local': sources.append({"title":"지방공무원 복무규정 · 기관 조례 추가 확인", "url":LOCAL,"scope":"시행 2026-10-02 · 적용 조항 추가 대조 필요"})
    return {"query":query,"mode":"leave_guide","model":None,"profile":None,
        "summary":summary,"answer":"","notice":None,"ai_note":None,"plan":None,
        "alternatives":[],"cited":[],"related":[],"personal_notes":[],
        "leave_guide":{"types":[{k:t[k] for k in ['id','title','group','description']} for t in TYPES],
          "selected":selected,"selection":"user" if leave_type else "candidate" if selected else "needs_choice",
          "context":{"personnel":personnel,"work_pattern":work,"subtype":subtype},
          "personnel_options":PERSONNEL,"work_options":WORK,"special_options":SPECIAL,
          "missing":missing,"scope":scope,"questions":(selected_type['questions']+([SPECIAL_QUESTIONS[subtype]] if selected=='special' and subtype else [])) if selected_type else [],
          "documents":selected_type['documents'] if selected_type else [],
          "basis":selected_type['basis'] if selected_type else "국가공무원 복무규정 제14조 · 휴가 종류, 제11조 · 휴무·시간외근무 연가 전환",
          "sources":sources,"checked_at":CHECKED,"entitlement_confirmed":False,
          "notice":"종류·준비사항 안내 단계입니다. 휴가 잔액·승인 가능 일수·신청 마감일·수당 중복 여부는 계산하거나 확정하지 않습니다."}}
