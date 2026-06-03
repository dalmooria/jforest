# tests/test_parser_notices.py
from pathlib import Path
from jforest.parsers.notices import parse_notice_list, find_tot_page, parse_notice_detail

FX = Path(__file__).parent / "fixtures"

def test_find_tot_page():
    body = (FX / "notice_list.html").read_text(encoding="utf-8")
    assert find_tot_page(body) >= 1

def test_parse_notice_list_extracts_twbbs_ids():
    body = (FX / "notice_list.html").read_text(encoding="utf-8")
    items = parse_notice_list(body)
    assert len(items) >= 1
    ids = {it["twbbs_id"] for it in items}
    assert "250396" in ids
    it = next(it for it in items if it["twbbs_id"] == "250396")
    assert it["title"] and "산불" in it["title"]

def test_parse_notice_detail_title_and_attachment():
    body = (FX / "notice_detail.html").read_text(encoding="utf-8")
    d = parse_notice_detail(body)
    assert "산불" in (d["title"] or "")
    assert d["body_text"] and len(d["body_text"]) > 5
    files = {(a["file_master_id"], a["file_id"]) for a in d["attachments"]}
    assert ("FILEMSTER_00172858", "184669") in files
    # 파일명도 같은 li의 span에서 추출
    att = next(a for a in d["attachments"] if a["file_id"] == "184669")
    assert att["file_name"] and att["file_name"].endswith(".pdf")
