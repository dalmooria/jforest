# tests/test_crawler_notices.py
import sqlite3, httpx
from pathlib import Path
from jforest.db import init_db
from jforest.http import Client
from jforest.crawlers.notices import run, download_attachments, sniff_content_type
from jforest.util import now_iso

FX = Path(__file__).parent / "fixtures"

def test_sniff_content_type_by_magic_bytes():
    assert sniff_content_type(b"\xff\xd8\xff\xe0rest", "x") == "image/jpeg"
    assert sniff_content_type(b"%PDF-1.7", "x") == "application/pdf"
    assert sniff_content_type(b"\x89PNG\r\n", "x") == "image/png"

def test_run_collects_notices_and_attachment_meta():
    list_body = (FX / "notice_list.html").read_text(encoding="utf-8")
    detail_body = (FX / "notice_detail.html").read_text(encoding="utf-8")
    def handler(request):
        if "selectNticBbrssListView" in request.url.path:
            return httpx.Response(200, text=list_body)
        if "selectNticBbrssDtlView" in request.url.path:
            return httpx.Response(200, text=detail_body)
        return httpx.Response(404)
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    conn.execute("INSERT INTO forests (instt_id, name, fetched_at) VALUES ('0113','가리왕산',?)", (now_iso(),)); conn.commit()
    client = Client(conn, delay=0, transport=httpx.MockTransport(handler))
    run(conn, client)
    nn = conn.execute("SELECT COUNT(*) FROM notices WHERE instt_id='0113'").fetchone()[0]
    assert nn >= 1
    na = conn.execute("SELECT COUNT(*) FROM notice_attachments").fetchone()[0]
    assert na >= 1  # 250396 상세에 첨부 1건
    fn = conn.execute("SELECT file_name FROM notice_attachments WHERE file_id='184669'").fetchone()
    assert fn and fn["file_name"] and fn["file_name"].endswith(".pdf")  # span에서 파일명 추출

def test_download_attachments_writes_file(tmp_path):
    def handler(request):
        return httpx.Response(200, content=b"%PDF-1.7 data",
                              headers={"Content-Type": "application/octet-stream",
                                       "Content-Disposition": "attachment; filename=a.pdf"})
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    conn.execute("INSERT INTO notice_attachments (instt_id, twbbs_id, file_master_id, file_id, file_name, downloaded, fetched_at) "
                 "VALUES ('0113','250396','FILEMSTER_1','184669','a.pdf',0,?)", (now_iso(),)); conn.commit()
    client = Client(conn, delay=0, transport=httpx.MockTransport(handler))
    download_attachments(conn, client, dest_dir=str(tmp_path))
    row = conn.execute("SELECT downloaded, local_path, content_type FROM notice_attachments").fetchone()
    assert row["downloaded"] == 1
    assert row["content_type"] == "application/pdf"
    assert Path(row["local_path"]).exists()
