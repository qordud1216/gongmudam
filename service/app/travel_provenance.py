"""사용자 등록 규정의 원문 보존과 대조 이력. 공식 계산팩 인증과 구분한다."""
import hashlib
import io
import json
from pathlib import PurePosixPath
from urllib.parse import urlsplit
from pypdf import PdfReader

MAX_BYTES=5*1024*1024


def validate_source(raw, filename, title, issuer, source_url):
    filename=filename.replace('\\','/').split('/')[-1]
    suffix=PurePosixPath(filename).suffix.lower()
    if not filename or len(filename)>180 or any(ord(c)<32 for c in filename):
        raise ValueError('파일명을 확인하세요. 180자 이하로 등록하세요.')
    if not 2<=len(title.strip())<=200 or not 2<=len(issuer.strip())<=150:
        raise ValueError('원문명·발행기관을 각각 2~200자·2~150자로 입력하세요.')
    if not raw or len(raw)>MAX_BYTES: raise ValueError('원문은 1바이트~5MB로 등록하세요.')
    source_url=source_url.strip()
    if source_url:
        parsed=urlsplit(source_url)
        if len(source_url)>1500 or parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in source_url):
            raise ValueError('출처 주소는 계정정보 없는 HTTP·HTTPS 주소를 입력하세요.')
    if suffix=='.txt':
        try: text=raw.decode('utf-8-sig')
        except UnicodeError as exc: raise ValueError('텍스트는 UTF-8 파일로 등록하세요.') from exc
        if '\x00' in text or not text.strip(): raise ValueError('정상적인 UTF-8 텍스트를 등록하세요.')
        media='text/plain'; pages=None
    elif suffix=='.pdf':
        if not raw.startswith(b'%PDF-'): raise ValueError('PDF 파일 형식이 일치하지 않습니다.')
        try:
            pdf=PdfReader(io.BytesIO(raw))
            if pdf.is_encrypted: raise ValueError('암호화 PDF는 해제한 사본으로 등록하세요.')
            pages=len(pdf.pages)
            if not 1<=pages<=1000: raise ValueError('PDF는 1~1,000쪽으로 등록하세요.')
        except ValueError: raise
        except Exception as exc: raise ValueError('정상 PDF인지 확인하세요.') from exc
        media='application/pdf'
    else: raise ValueError('기관 규정 원문은 PDF·UTF-8 TXT를 지원합니다.')
    return {'filename':filename,'title':title.strip(),'issuer':issuer.strip(),'source_url':source_url,
            'media_type':media,'extension':suffix,'pages':pages,'sha256':hashlib.sha256(raw).hexdigest(),
            'size':len(raw),'notice':'사용자 등록 원문 · 공식 진위·법적 적합성 미인증. 출처 주소를 서버에서 가져오지 않습니다.'}


def source_view(row):
    result=json.loads(row['metadata_json'])
    result.update(id=row['id'],organization_id=row['organization_id'],created_at=row['created_at'])
    result['original_url']=f"/api/travel/organizations/{row['organization_id']}/rule-sources/{row['id']}/original"
    return result


def attach_reviews(c, rules):
    for rule in rules:
        history=[]
        for row in c.execute('SELECT * FROM travel_rule_reviews WHERE rule_id=? ORDER BY revision',(rule['id'],)):
            r=json.loads(row['review_json']);r.update(id=row['id'],revision=row['revision'],created_at=row['created_at'])
            source=c.execute('SELECT id,organization_id,metadata_json,created_at FROM travel_rule_sources WHERE id=?',(row['source_id'],)).fetchone()
            r['source']=source_view(source);history.append(r)
        if history:
            rule['review_history']=history
            rule['user_review']=history[-1]
    return rules
