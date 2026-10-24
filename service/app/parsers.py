"""문서 파서: hwp, hwpx, pdf, xlsx, docx, txt/md/csv 를 '단위(unit)' 목록으로 바꾼다.

단위 = {"text": 본문, "loc": 사람이 읽는 위치(예: "3쪽", "시트 '일정' 5행", "12번째 문단")}
원본 파일은 읽기 전용으로 열며 절대 수정하지 않는다.
"""
from __future__ import annotations

import csv
import io
import re
import struct
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET

SUPPORTED = {".hwp", ".hwpx", ".pdf", ".xlsx", ".xlsm", ".docx", ".txt", ".md", ".csv"}


class ParseError(RuntimeError):
    pass


def parse_file(path: Path) -> list[dict]:
    ext = path.suffix.lower()
    fn = {
        ".hwp": _parse_hwp, ".hwpx": _parse_hwpx, ".pdf": _parse_pdf,
        ".xlsx": _parse_xlsx, ".xlsm": _parse_xlsx, ".docx": _parse_docx,
        ".txt": _parse_text, ".md": _parse_text, ".csv": _parse_csv,
    }.get(ext)
    if fn is None:
        raise ParseError(f"지원하지 않는 형식: {ext}")
    units = fn(path)
    return [u for u in units if u["text"].strip()]


# ---------------------------------------------------------------- 텍스트
def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_text(path: Path) -> list[dict]:
    lines = _read_text(path).splitlines()
    return [{"text": ln.strip(), "loc": f"{i}행"} for i, ln in enumerate(lines, 1) if ln.strip()]


def _parse_csv(path: Path) -> list[dict]:
    rows = list(csv.reader(io.StringIO(_read_text(path))))
    return _rows_to_units(rows, sheet=None)


def _rows_to_units(rows: list[list], sheet: str | None) -> list[dict]:
    """첫 행을 머리글로 보고 각 행을 '머리글: 값' 문장으로 만든다."""
    units = []
    rows = [[("" if c is None else str(c).strip()) for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return units
    header = rows[0]
    prefix = f"시트 '{sheet}' " if sheet else ""
    for idx, r in enumerate(rows[1:], 2):
        parts = []
        for h, v in zip(header, r):
            if v:
                parts.append(f"{h}: {v}" if h else v)
        if parts:
            units.append({"text": " / ".join(parts), "loc": f"{prefix}{idx}행"})
    return units


# ---------------------------------------------------------------- 엑셀
def _parse_xlsx(path: Path) -> list[dict]:
    import openpyxl
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"엑셀을 열 수 없습니다: {e}") from e
    units = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append([_cell(c) for c in row])
        units += _rows_to_units(rows, ws.title)
    wb.close()
    return units


def _cell(v):
    if v is None:
        return ""
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    return str(v)


# ---------------------------------------------------------------- PDF
def _parse_pdf(path: Path) -> list[dict]:
    from pypdf import PdfReader
    try:
        reader = PdfReader(str(path))
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"PDF를 열 수 없습니다: {e}") from e
    units = []
    for pno, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        for para in _split_paragraphs(text):
            units.append({"text": para, "loc": f"{pno}쪽"})
    return units


def _split_paragraphs(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines()]
    out, buf = [], []
    for ln in lines:
        if not ln:
            if buf:
                out.append(" ".join(buf))
                buf = []
            continue
        # 번호·기호로 시작하면 새 문단으로 본다
        if buf and re.match(r"^([0-9]+[.)]|[가-하][.)]|[□○◦▶\-•※]|제\s*\d+\s*조)", ln):
            out.append(" ".join(buf))
            buf = []
        buf.append(ln)
    if buf:
        out.append(" ".join(buf))
    return out


# ---------------------------------------------------------------- DOCX
def _parse_docx(path: Path) -> list[dict]:
    try:
        z = zipfile.ZipFile(path)
        xml = z.read("word/document.xml")
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"DOCX를 열 수 없습니다: {e}") from e
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ET.fromstring(xml)
    units = []
    for i, p in enumerate(root.iter(ns + "p"), 1):
        t = "".join(x.text or "" for x in p.iter(ns + "t")).strip()
        if t:
            units.append({"text": t, "loc": f"{i}번째 문단"})
    return units


# ---------------------------------------------------------------- HWPX (OWPML, zip+xml)
def _parse_hwpx(path: Path) -> list[dict]:
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise ParseError("HWPX 파일 구조가 올바르지 않습니다.") from e
    sections = sorted(
        (n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
        key=lambda n: int(re.findall(r"\d+", n)[-1]),
    )
    if not sections:
        raise ParseError("HWPX 본문(section)이 없습니다.")
    units, n = [], 0
    for sec in sections:
        root = ET.fromstring(z.read(sec))
        for p in root.iter():
            if not p.tag.endswith("}p"):
                continue
            # 표 안의 문단은 바깥 문단과 별도로 수집되므로 직속 run 의 글자만 모은다
            texts = []
            for run in p:
                if not run.tag.endswith("}run"):
                    continue
                for t in run:
                    if t.tag.endswith("}t"):
                        texts.append("".join(t.itertext()))
            line = "".join(texts).strip()
            if line:
                n += 1
                units.append({"text": line, "loc": f"{n}번째 문단"})
    return units


# ---------------------------------------------------------------- HWP 5.0 (OLE 바이너리)
HWPTAG_PARA_TEXT = 0x10 + 51
_EXT_CTRL = {1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23}
_INLINE_CTRL = {4, 5, 6, 7, 8, 9, 19, 20}


def _parse_hwp(path: Path) -> list[dict]:
    import olefile
    if not olefile.isOleFile(str(path)):
        raise ParseError("HWP 5.0 형식이 아닙니다 (HWP 3.0 이하는 미지원).")
    ole = olefile.OleFileIO(str(path))
    try:
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack("<I", header[36:40])[0]
        compressed, encrypted, distribute = flags & 1, flags & 2, flags & 4
        if encrypted:
            raise ParseError("암호가 걸린 HWP 문서입니다.")
        storage = "ViewText" if distribute else "BodyText"
        if distribute:
            raise ParseError("배포용 HWP 문서는 본문을 읽을 수 없습니다.")
        secs = sorted(
            (e for e in ole.listdir() if e[0] == storage and e[1].startswith("Section")),
            key=lambda e: int(e[1][7:]),
        )
        units, n = [], 0
        for entry in secs:
            data = ole.openstream(entry).read()
            if compressed:
                data = zlib.decompress(data, -15)
            for line in _hwp_records_text(data):
                line = line.strip()
                if line:
                    n += 1
                    units.append({"text": line, "loc": f"{n}번째 문단"})
        return units
    finally:
        ole.close()


def _hwp_records_text(data: bytes):
    pos, size = 0, len(data)
    while pos + 4 <= size:
        hdr = struct.unpack("<I", data[pos:pos + 4])[0]
        pos += 4
        tag, length = hdr & 0x3FF, (hdr >> 20) & 0xFFF
        if length == 0xFFF:
            length = struct.unpack("<I", data[pos:pos + 4])[0]
            pos += 4
        payload = data[pos:pos + length]
        pos += length
        if tag == HWPTAG_PARA_TEXT:
            yield _hwp_para_text(payload)


def _hwp_para_text(payload: bytes) -> str:
    out, i, n = [], 0, len(payload) // 2
    while i < n:
        ch = struct.unpack("<H", payload[i * 2:i * 2 + 2])[0]
        if ch < 32:
            if ch in _EXT_CTRL or ch in _INLINE_CTRL:
                if ch == 9:  # 탭도 8글자 크기의 인라인 컨트롤
                    out.append("\t")
                i += 8
                continue
            if ch in (10, 13):
                out.append("\n")
            i += 1
            continue
        out.append(chr(ch))
        i += 1
    return "".join(out)
