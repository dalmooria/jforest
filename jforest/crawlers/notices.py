# jforest/crawlers/notices.py
import os

from jforest.http import BASE
from jforest.db import save_raw
from jforest.parsers.notices import parse_notice_list, find_tot_page, parse_notice_detail
from jforest.util import now_iso, Summary

LIST_URL = f"{BASE}/pot/cc/nm/selectNticBbrssListView.do"
DTL_URL = f"{BASE}/pot/cc/nm/selectNticBbrssDtlView.do"
FILE_URL = f"{BASE}/com/cm/fileDownload.do"
BBRSS = "BBRSSMSTER_00000051"

_MAGIC = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"%PDF", "application/pdf"),
    (b"\x89PNG\r\n", "image/png"),
    (b"GIF8", "image/gif"),
    (b"PK\x03\x04", "application/zip"),  # hwpx/docx/xlsx 포함
]


def sniff_content_type(content: bytes, fallback: str) -> str:
    for sig, ct in _MAGIC:
        if content.startswith(sig):
            return ct
    return fallback


def run(conn, client, *, limit=None, force=False) -> Summary:
    s = Summary()
    forests = list(conn.execute("SELECT instt_id FROM forests ORDER BY instt_id"))
    if limit:
        forests = forests[:limit]
    for f in forests:
        iid = f["instt_id"]
        status, body = client.get(LIST_URL, params={
            "hmpgId": iid, "menuId": "005001", "bbrssMsterId": BBRSS, "nowPage": 1})
        save_raw(conn, LIST_URL, "notice_list", f"{iid}:1", status, body, now_iso())
        if status != 200:
            s.failed += 1; s.failures.append(f"{iid} list HTTP {status}"); continue
        tot = find_tot_page(body)
        all_items = parse_notice_list(body)
        for page in range(2, tot + 1):
            st, bd = client.get(LIST_URL, params={
                "hmpgId": iid, "menuId": "005001", "bbrssMsterId": BBRSS, "nowPage": page})
            save_raw(conn, LIST_URL, "notice_list", f"{iid}:{page}", st, bd, now_iso())
            if st == 200:
                all_items.extend(parse_notice_list(bd))
        for it in all_items:
            twbbs = it["twbbs_id"]
            if not force:
                done = conn.execute(
                    "SELECT 1 FROM notices WHERE instt_id=? AND twbbs_id=?", (iid, twbbs)
                ).fetchone()
                if done:
                    s.skipped += 1; continue
            dstatus, dbody = client.get(DTL_URL, params={
                "hmpgId": iid, "menuId": "005001", "twbbsId": twbbs, "bbrssMsterId": BBRSS})
            save_raw(conn, DTL_URL, "notice_detail", f"{iid}:{twbbs}", dstatus, dbody, now_iso())
            if dstatus != 200:
                s.failed += 1; s.failures.append(f"{iid}/{twbbs} HTTP {dstatus}"); continue
            d = parse_notice_detail(dbody)
            ts = now_iso()
            conn.execute(
                "INSERT OR REPLACE INTO notices (instt_id, twbbs_id, title, updated_at, body_text, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (iid, twbbs, d["title"] or it["title"], d["updated_at"] or it["updated_at"], d["body_text"], ts),
            )
            for a in d["attachments"]:
                conn.execute(
                    "INSERT OR REPLACE INTO notice_attachments "
                    "(instt_id, twbbs_id, file_master_id, file_id, file_name, content_type, local_path, downloaded, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, NULL, NULL, 0, ?)",
                    (iid, twbbs, a["file_master_id"], a["file_id"], a.get("file_name"), ts),
                )
            conn.commit()
            s.ok += 1
    return s


def download_attachments(conn, client, *, dest_dir="data/attachments", limit=None):
    s = Summary()
    os.makedirs(dest_dir, exist_ok=True)
    pending = list(conn.execute("SELECT * FROM notice_attachments WHERE downloaded=0"))
    if limit:
        pending = pending[:limit]
    for a in pending:
        status, content, headers = client.download(FILE_URL, params={
            "ATTCH_FILE_ID": a["file_id"], "ATTCH_FILE_MSTER_ID": a["file_master_id"]})
        if status != 200 or not content:
            s.failed += 1; s.failures.append(f"file {a['file_id']} HTTP {status}"); continue
        ct = sniff_content_type(content, headers.get("Content-Type", "application/octet-stream"))
        fname = a["file_name"] or f"{a['file_master_id']}_{a['file_id']}"
        path = os.path.join(dest_dir, f"{a['file_master_id']}_{a['file_id']}_{os.path.basename(fname)}")
        with open(path, "wb") as fh:
            fh.write(content)
        conn.execute(
            "UPDATE notice_attachments SET downloaded=1, local_path=?, content_type=? WHERE id=?",
            (path, ct, a["id"]),
        )
        conn.commit()
        s.ok += 1
    return s
