# tests/test_extract.py
import sqlite3
import zipfile
from jforest.db import init_db
from jforest.extract import (
    run_pdf_text_extraction,
    extract_hwpx_text, run_hwpx_text_extraction,
    extract_hwp_text, run_hwp_text_extraction,
    run_vision_ocr,
)
from jforest.util import now_iso


def _make_hwpx(path, text):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("version.xml", "<x/>")
        z.writestr("Preview/PrvText.txt", text)


def _att(conn, aid, ct, path):
    conn.execute(
        "INSERT INTO notice_attachments "
        "(id, instt_id, twbbs_id, file_master_id, file_id, content_type, local_path, downloaded, fetched_at) "
        "VALUES (?, '0113', '1', ?, ?, ?, ?, 1, ?)",
        (aid, f"FM{aid}", str(aid), ct, path, now_iso()),
    )


def test_run_pdf_text_extraction_stores_text():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _att(conn, 1, "application/pdf", "/x/a.pdf"); conn.commit()
    n = run_pdf_text_extraction(conn, extractor=lambda p: "공지 본문 텍스트가 충분히 길게 들어있는 내용")
    assert n == 1
    row = conn.execute("SELECT extracted_text, extraction_method FROM notice_attachments WHERE id=1").fetchone()
    assert "공지 본문" in row["extracted_text"]
    assert row["extraction_method"] == "pdftext"


def test_run_pdf_text_extraction_flags_scanned_as_needs_ocr():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _att(conn, 1, "application/pdf", "/x/a.pdf"); conn.commit()
    n = run_pdf_text_extraction(conn, extractor=lambda p: "  ")  # 스캔 PDF: 텍스트 레이어 없음
    assert n == 1
    row = conn.execute("SELECT extraction_method FROM notice_attachments WHERE id=1").fetchone()
    assert row["extraction_method"] == "needs_ocr"


def test_run_pdf_text_extraction_skips_non_pdf_and_already_done():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _att(conn, 1, "image/jpeg", "/x/a.jpg")           # 이미지 → PDF 추출 대상 아님
    _att(conn, 2, "application/pdf", "/x/b.pdf")
    conn.execute("UPDATE notice_attachments SET extracted_text='이미함', extraction_method='pdftext' WHERE id=2")
    conn.commit()
    n = run_pdf_text_extraction(conn, extractor=lambda p: (_ for _ in ()).throw(AssertionError("불려선 안 됨")))
    assert n == 0


def test_extract_hwpx_text_reads_prvtext(tmp_path):
    p = tmp_path / "a.hwpx"
    _make_hwpx(str(p), "2026년 봄철 산불조심기간 공고 본문 내용")
    assert "산불조심기간" in extract_hwpx_text(str(p))


def test_extract_hwpx_text_returns_empty_for_non_hwpx_zip(tmp_path):
    p = tmp_path / "a.zip"
    with zipfile.ZipFile(str(p), "w") as z:
        z.writestr("xl/workbook.xml", "<x/>")  # xlsx 등 비-hwpx
    assert extract_hwpx_text(str(p)) == ""


def test_run_hwpx_text_extraction_stores_text(tmp_path):
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    p = tmp_path / "a.hwpx"
    _make_hwpx(str(p), "산불조심기간 공고문 본문이 충분히 길게 들어있는 내용입니다")
    _att(conn, 1, "application/zip", str(p)); conn.commit()
    n = run_hwpx_text_extraction(conn)
    assert n == 1
    row = conn.execute("SELECT extracted_text, extraction_method FROM notice_attachments WHERE id=1").fetchone()
    assert "산불조심기간" in row["extracted_text"]
    assert row["extraction_method"] == "hwpx"


def test_run_hwpx_text_extraction_marks_non_hwpx_unsupported(tmp_path):
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    p = tmp_path / "a.zip"
    with zipfile.ZipFile(str(p), "w") as z:
        z.writestr("xl/workbook.xml", "<x/>")
    _att(conn, 1, "application/zip", str(p)); conn.commit()
    run_hwpx_text_extraction(conn)
    row = conn.execute("SELECT extraction_method FROM notice_attachments WHERE id=1").fetchone()
    assert row["extraction_method"] == "unsupported"


def test_extract_hwp_text_reads_prvtext_stream():
    from pathlib import Path
    fx = Path(__file__).parent / "fixtures" / "sample.hwp"
    text = extract_hwp_text(str(fx))
    assert "입장" in text and "요금" in text


def test_extract_hwp_text_returns_empty_for_non_ole(tmp_path):
    p = tmp_path / "a.hwp"
    p.write_bytes(b"not an ole file")
    assert extract_hwp_text(str(p)) == ""


def test_run_hwp_text_extraction_stores_text():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _att(conn, 1, "application/x-ole-storage; charset=UTF-8", "/x/a.hwp"); conn.commit()
    n = run_hwp_text_extraction(conn, extractor=lambda p: "휴양림 입장 요금표 본문이 충분히 길게 들어있는 내용")
    assert n == 1
    row = conn.execute("SELECT extracted_text, extraction_method FROM notice_attachments WHERE id=1").fetchone()
    assert "요금표" in row["extracted_text"]
    assert row["extraction_method"] == "hwp"


def test_run_hwp_text_extraction_flags_no_prvtext_as_needs_ocr():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _att(conn, 1, "application/x-hwp; charset=UTF-8", "/x/a.hwp"); conn.commit()
    run_hwp_text_extraction(conn, extractor=lambda p: "")  # PrvText 없음
    row = conn.execute("SELECT extraction_method FROM notice_attachments WHERE id=1").fetchone()
    assert row["extraction_method"] == "needs_ocr"


def test_run_vision_ocr_stores_image_text():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _att(conn, 1, "image/jpeg", "/x/a.jpg"); conn.commit()
    n = run_vision_ocr(conn, ocr_file=lambda p, ct: "이미지에서 추출한 한국어 공지 텍스트")
    assert n == 1
    row = conn.execute("SELECT extracted_text, extraction_method FROM notice_attachments WHERE id=1").fetchone()
    assert "한국어" in row["extracted_text"]
    assert row["extraction_method"] == "vision"


def test_run_vision_ocr_reprocesses_needs_ocr_pdf():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _att(conn, 1, "application/pdf", "/x/a.pdf")
    conn.execute("UPDATE notice_attachments SET extracted_text='', extraction_method='needs_ocr' WHERE id=1")
    conn.commit()
    n = run_vision_ocr(conn, ocr_file=lambda p, ct: "스캔본 PDF를 OCR해서 추출한 충분히 긴 한국어 결과 텍스트")
    assert n == 1
    row = conn.execute("SELECT extraction_method FROM notice_attachments WHERE id=1").fetchone()
    assert row["extraction_method"] == "vision"


def test_run_vision_ocr_skips_video_and_already_done():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _att(conn, 1, "video/mp4; charset=UTF-8", "/x/a.mp4")          # 동영상 → OCR 대상 아님
    _att(conn, 2, "image/png", "/x/b.png")
    conn.execute("UPDATE notice_attachments SET extracted_text='이미', extraction_method='vision' WHERE id=2")
    conn.commit()
    n = run_vision_ocr(conn, ocr_file=lambda p, ct: (_ for _ in ()).throw(AssertionError("불려선 안 됨")))
    assert n == 0


def test_run_vision_ocr_isolates_per_file_errors():
    # 한 파일(손상 PDF 등)에서 예외가 나도 전체 실행이 멈추면 안 되고, 그 파일만 표시한다.
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _att(conn, 1, "image/jpeg", "/x/bad.jpg")
    _att(conn, 2, "image/png", "/x/good.png")
    conn.commit()

    def ocr(p, ct):
        if "bad" in p:
            raise RuntimeError("pdftoppm/vision 실패")
        return "정상 OCR 텍스트가 충분히 길게 추출됨"

    n = run_vision_ocr(conn, ocr_file=ocr)
    assert n == 2
    bad = conn.execute("SELECT extraction_method FROM notice_attachments WHERE id=1").fetchone()
    good = conn.execute("SELECT extraction_method FROM notice_attachments WHERE id=2").fetchone()
    assert bad["extraction_method"] == "vision_error"
    assert good["extraction_method"] == "vision"


def test_run_vision_ocr_skips_needs_ocr_hwp_not_pdf():
    # PrvText 없는 .hwp(바이너리)는 래스터화 불가 → vision 대상에서 제외돼야 한다.
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _att(conn, 1, "application/x-ole-storage; charset=UTF-8", "/x/a.hwp")
    conn.execute("UPDATE notice_attachments SET extracted_text='', extraction_method='needs_ocr' WHERE id=1")
    conn.commit()
    n = run_vision_ocr(conn, ocr_file=lambda p, ct: (_ for _ in ()).throw(AssertionError("불려선 안 됨")))
    assert n == 0


def test_init_db_migrates_extract_columns_onto_existing_attachments():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE notice_attachments (id INTEGER PRIMARY KEY, instt_id TEXT NOT NULL, twbbs_id TEXT NOT NULL, "
        "file_master_id TEXT, file_id TEXT, file_name TEXT, content_type TEXT, local_path TEXT, "
        "downloaded INTEGER DEFAULT 0, fetched_at TEXT NOT NULL, UNIQUE (file_master_id, file_id))"
    )
    conn.commit()
    init_db(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(notice_attachments)")]
    assert "extracted_text" in cols
    assert "extraction_method" in cols
