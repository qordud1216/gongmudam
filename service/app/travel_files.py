"""로컬 증빙 읽기. 원본을 실행하지 않으며 OCR 결과와 거래 확정은 분리한다."""
import io
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from pypdf import PdfReader
from .travel_engine import parse_evidence, DATE_RE, TIME_RE

MAX_BYTES=10*1024*1024
MAX_TEXT=30000
TYPES={'.pdf':'application/pdf','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg'}


class ReceiptError(ValueError): pass


def read_receipt(raw, extension):
    if extension not in TYPES: raise ReceiptError('PDF·PNG·JPG 파일만 지원합니다.')
    if not raw or len(raw)>MAX_BYTES: raise ReceiptError('파일 크기는 1바이트~10MB여야 합니다.')
    signature=raw.startswith(b'%PDF-') if extension=='.pdf' else raw.startswith(b'\x89PNG\r\n\x1a\n') if extension=='.png' else raw.startswith(b'\xff\xd8\xff')
    if not signature: raise ReceiptError('확장자와 파일 형식이 일치하지 않습니다.')
    if extension=='.pdf':
        try:
            reader=PdfReader(io.BytesIO(raw))
            if reader.is_encrypted: raise ReceiptError('암호화 PDF는 해제한 사본으로 등록하세요.')
            if len(reader.pages)>10: raise ReceiptError('한 파일당 10쪽 이하 PDF를 등록하세요.')
            pages=[]; total=0
            for i,page in enumerate(reader.pages):
                text=page.extract_text() or ''; total+=len(text)
                if total>MAX_TEXT: raise ReceiptError('추출 문자가 30,000자를 넘습니다. 필요한 영수증만 분리하세요.')
                pages.append({'page':i+1,'text':text})
            scanned=[p['page'] for p in pages if not p['text'].strip()]
            return {'engine':'pypdf','text':'\n'.join(p['text'] for p in pages),'pages':pages,
                    'warnings':[f"텍스트 없는 쪽 {', '.join(map(str,scanned))}: 스캔 PDF는 해당 쪽을 이미지로 저장해 OCR하거나 거래를 직접 입력하세요."] if scanned else []}
        except ReceiptError: raise
        except Exception as exc: raise ReceiptError('PDF를 읽지 못했습니다. 정상 파일인지 확인하세요.') from exc
    if os.name!='nt':
        return {'engine':'manual','text':'','pages':[],'warnings':['이 환경은 Windows OCR을 지원하지 않습니다. 원본을 보고 거래를 직접 입력하세요.']}
    with tempfile.TemporaryDirectory(prefix='seomu_receipt_') as folder:
        path=Path(folder)/('receipt'+extension);path.write_bytes(raw)
        try:
            script=Path(__file__).with_name('windows_receipt_ocr.ps1').read_text(encoding='utf-8')
            # 고정된 앱 코드만 실행한다. 파일 경로는 코드에 삽입하지 않고 환경변수로 전달한다.
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command','& {\n'+script+'\n} -ImagePath $env:SEOMU_RECEIPT_PATH'],env={**os.environ,'SEOMU_RECEIPT_PATH':str(path)},capture_output=True,timeout=35,creationflags=0x08000000)
            data=json.loads(result.stdout.decode('utf-8-sig'))
        except subprocess.TimeoutExpired:
            return {'engine':'manual','text':'','pages':[],'warnings':['OCR 제한시간을 넘었습니다. 이미지를 줄이거나 원본을 보고 직접 입력하세요.']}
        except (OSError,ValueError):
            return {'engine':'manual','text':'','pages':[],'warnings':['OCR을 실행하지 못했습니다. 원본을 보고 거래를 직접 입력하세요.']}
    if data.get('error'):
        if 'IMAGE_TOO_LARGE' in data['error']: raise ReceiptError('이미지가 너무 큽니다. 2천만 화소 이하·OCR 허용 크기로 줄이세요.')
        if 'OCR_UNAVAILABLE' in data['error']:
            return {'engine':'manual','text':'','pages':[],'warnings':['Windows OCR 언어팩이 없습니다. 원본을 보고 직접 입력하세요.']}
        raise ReceiptError('이미지를 읽지 못했습니다. 정상 PNG·JPG 파일인지 확인하세요.')
    if len(data['text'])>MAX_TEXT: raise ReceiptError('OCR 문자가 30,000자를 넘습니다.')
    return {'engine':data['engine'],'language':data['language'],'text':data['text'],'pages':[{'page':1,'text':data['text']}],
            'warnings':['OCR은 날짜·숫자·취소 표시를 잘못 읽을 수 있습니다. 원본과 대조하세요.']}


def suggest_transactions(text,start,end):
    # 한 줄 거래는 그대로 제안한다. 영수증 본문은 명시적 라벨이 있는 단일 거래만 지원한다.
    rows,issues=parse_evidence(text,start,end,'receipt_text')
    if rows and not issues:
        return text,[]
    dates={m.group(0) for m in DATE_RE.finditer(text)}
    merchants=re.findall(r'(?m)^\s*(?:가맹점|상호명|상호)(?:\s*[:：]\s*|\s+)([^\r\n]+)',text)
    totals=re.findall(r'(?m)^\s*(?:합계|결제금액|승인금액|총액)\s*[:：]?\s*((?:\d{1,3}(?:,\d{3})+|\d+)\s*원)\s*$',text)
    if len(dates)==1 and len(set(merchants))==1 and len(set(totals))==1:
        times={m.group(0) for m in TIME_RE.finditer(text)}
        if len(times)>1: return '',['시각이 여러 개입니다. 원본을 보고 거래별로 입력하세요.']
        canonical=f"{next(iter(dates))} {next(iter(times),'')} {merchants[0]} {totals[0]}"+(' 취소' if '취소' in text else '')
        parsed,failed=parse_evidence(canonical,start,end,'receipt_text')
        if parsed and not failed:
            return canonical,['날짜·상호·최종 금액 라벨을 이용한 후보입니다. 원본 전체와 대조하고 취소 여부도 확인하세요.']
    return '',['자동으로 거래를 특정하지 못했습니다. 원본의 날짜·가맹점·결제금액·취소 여부를 보고 거래를 직접 입력하세요.']
