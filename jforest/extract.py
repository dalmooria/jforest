# jforest/extract.py
"""첨부파일 텍스트/구조화 추출 (Stage 1: 무료 텍스트 레이어).

Stage 1은 비용 없이 가능한 텍스트 추출만 수행한다.
- PDF: pdftotext로 텍스트 레이어 추출. 텍스트가 거의 없으면 스캔본으로 보고 needs_ocr 표시.
이미지/스캔 PDF의 OCR(Stage 2)과 구조화(Stage 3)는 별도 단계.
"""
import re
import subprocess
import zipfile

import olefile

_MIN_CHARS = 20  # 이보다 짧으면 스캔본(텍스트 레이어 없음)으로 보고 OCR 대상으로 돌린다.


def extract_pdf_text(path: str) -> str:
    """pdftotext로 PDF 텍스트 레이어를 추출한다(레이아웃 보존)."""
    r = subprocess.run(
        ["pdftotext", "-layout", path, "-"],
        capture_output=True, text=True, timeout=120,
    )
    return r.stdout.strip()


def extract_hwpx_text(path: str) -> str:
    """HWPX(zip) 첨부에서 텍스트를 추출한다. 비-HWPX(zip)면 빈 문자열.

    우선 Preview/PrvText.txt(플레인 텍스트 미리보기)를 쓰고, 없으면 Contents/section*.xml의
    <hp:t> 텍스트 런을 모은다.
    """
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        return ""
    names = z.namelist()
    if "Preview/PrvText.txt" in names:
        return z.read("Preview/PrvText.txt").decode("utf-8", "replace").strip()
    secs = sorted(n for n in names if n.startswith("Contents/section") and n.endswith(".xml"))
    if secs:
        runs = []
        for n in secs:
            xml = z.read(n).decode("utf-8", "replace")
            runs.extend(re.findall(r"<hp:t>(.*?)</hp:t>", xml, re.S))
        text = re.sub(r"<[^>]+>", "", " ".join(runs))
        return text.strip()
    return ""


def run_hwpx_text_extraction(conn, *, extractor=extract_hwpx_text, min_chars=_MIN_CHARS, limit=None) -> int:
    """다운로드된 zip(HWPX) 첨부의 텍스트를 추출해 저장한다. 처리 건수 반환.

    HWPX면 extraction_method='hwpx', 추출 불가(xlsx 등)면 'unsupported'.
    """
    rows = list(conn.execute(
        "SELECT id, local_path FROM notice_attachments "
        "WHERE downloaded=1 AND extracted_text IS NULL "
        "AND content_type LIKE 'application/zip%' "
        "ORDER BY id"
    ))
    if limit:
        rows = rows[:limit]
    n = 0
    for r in rows:
        text = extractor(r["local_path"]).strip()
        method = "hwpx" if len(text) >= min_chars else "unsupported"
        conn.execute(
            "UPDATE notice_attachments SET extracted_text=?, extraction_method=? WHERE id=?",
            (text, method, r["id"]),
        )
        n += 1
    conn.commit()
    return n


def extract_hwp_text(path: str) -> str:
    """HWP 5.0(.hwp, OLE) 첨부의 PrvText 스트림(UTF-16LE)에서 텍스트를 추출한다.

    PrvText 스트림이 없거나 OLE가 아니면 빈 문자열(BodyText 압축 해제는 미지원).
    """
    if not olefile.isOleFile(path):
        return ""
    try:
        ole = olefile.OleFileIO(path)
    except OSError:
        return ""
    try:
        if not ole.exists("PrvText"):
            return ""
        return ole.openstream("PrvText").read().decode("utf-16-le", "replace").strip()
    finally:
        ole.close()


def run_hwp_text_extraction(conn, *, extractor=extract_hwp_text, min_chars=_MIN_CHARS, limit=None) -> int:
    """다운로드된 .hwp(OLE) 첨부의 텍스트를 추출해 저장한다. 처리 건수 반환.

    PrvText로 텍스트를 얻으면 extraction_method='hwp', 없으면 'needs_ocr'(Stage 2 대상).
    """
    rows = list(conn.execute(
        "SELECT id, local_path FROM notice_attachments "
        "WHERE downloaded=1 AND extracted_text IS NULL "
        "AND (content_type LIKE 'application/x-ole-storage%' OR content_type LIKE 'application/x-hwp%') "
        "ORDER BY id"
    ))
    if limit:
        rows = rows[:limit]
    n = 0
    for r in rows:
        text = extractor(r["local_path"]).strip()
        method = "hwp" if len(text) >= min_chars else "needs_ocr"
        conn.execute(
            "UPDATE notice_attachments SET extracted_text=?, extraction_method=? WHERE id=?",
            (text, method, r["id"]),
        )
        n += 1
    conn.commit()
    return n


def _vision_ocr_image(path: str, _client_box=[]) -> str:
    """Cloud Vision DOCUMENT_TEXT_DETECTION으로 이미지에서 한국어 텍스트를 추출한다.

    GOOGLE_APPLICATION_CREDENTIALS(서비스계정 JSON)가 설정돼 있어야 한다.
    클라이언트는 최초 호출 시 한 번만 생성한다.
    """
    from google.cloud import vision
    if not _client_box:
        _client_box.append(vision.ImageAnnotatorClient())
    client = _client_box[0]
    with open(path, "rb") as f:
        image = vision.Image(content=f.read())
    resp = client.document_text_detection(image=image, image_context={"language_hints": ["ko"]})
    if resp.error.message:
        raise RuntimeError(f"Cloud Vision error: {resp.error.message}")
    return (resp.full_text_annotation.text or "").strip()


def _vision_ocr_pdf(path: str, ocr_image=_vision_ocr_image) -> str:
    """스캔 PDF를 pdftoppm으로 페이지 이미지화한 뒤 각 페이지를 OCR해 합친다."""
    import glob
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(
            ["pdftoppm", "-r", "200", "-png", path, os.path.join(td, "p")],
            check=True, timeout=300, capture_output=True,
        )
        pages = sorted(glob.glob(os.path.join(td, "p*.png")))
        return "\n".join(ocr_image(pg) for pg in pages).strip()


def _default_ocr_file(path: str, content_type: str) -> str:
    if content_type.startswith("image/"):
        return _vision_ocr_image(path)
    return _vision_ocr_pdf(path)  # needs_ocr 스캔 PDF


def run_vision_ocr(conn, *, ocr_file=_default_ocr_file, min_chars=_MIN_CHARS, limit=None) -> int:
    """Cloud Vision OCR 대상(이미지 + needs_ocr 스캔PDF)을 OCR해 저장한다. 처리 건수 반환.

    - 이미지(image/*)로 아직 추출 안 된 것
    - 앞 단계에서 needs_ocr로 표시된 스캔 PDF
    성공 시 extraction_method='vision', 결과가 비면 'vision_empty'.
    """
    rows = list(conn.execute(
        "SELECT id, local_path, content_type FROM notice_attachments "
        "WHERE downloaded=1 AND ("
        "  (content_type LIKE 'image/%' AND extracted_text IS NULL) "
        "  OR (extraction_method='needs_ocr' AND content_type LIKE 'application/pdf%')"
        ") ORDER BY id"
    ))
    if limit:
        rows = rows[:limit]
    n = 0
    for r in rows:
        try:
            text = ocr_file(r["local_path"], r["content_type"] or "").strip()
            method = "vision" if len(text) >= min_chars else "vision_empty"
        except Exception:
            # 손상 파일 등 개별 오류는 격리해 표시하고 나머지는 계속 처리한다.
            text, method = "", "vision_error"
        conn.execute(
            "UPDATE notice_attachments SET extracted_text=?, extraction_method=? WHERE id=?",
            (text, method, r["id"]),
        )
        n += 1
        conn.commit()
    return n


def run_pdf_text_extraction(conn, *, extractor=extract_pdf_text, min_chars=_MIN_CHARS, limit=None) -> int:
    """다운로드된 PDF 첨부 중 아직 추출 안 된 것의 텍스트를 추출해 저장한다. 처리 건수 반환.

    추출 텍스트가 min_chars 미만이면 extraction_method='needs_ocr'로 표시(Stage 2 대상).
    """
    rows = list(conn.execute(
        "SELECT id, local_path FROM notice_attachments "
        "WHERE downloaded=1 AND extracted_text IS NULL "
        "AND content_type LIKE 'application/pdf%' "
        "ORDER BY id"
    ))
    if limit:
        rows = rows[:limit]
    n = 0
    for r in rows:
        text = extractor(r["local_path"]).strip()
        method = "pdftext" if len(text) >= min_chars else "needs_ocr"
        conn.execute(
            "UPDATE notice_attachments SET extracted_text=?, extraction_method=? WHERE id=?",
            (text, method, r["id"]),
        )
        n += 1
    conn.commit()
    return n
