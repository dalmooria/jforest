# jforest/parsers/notices.py
import re

from selectolax.parser import HTMLParser

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DTL = re.compile(r"fn_goDtlView\('(\d+)'\)")
_FILE = re.compile(r"fn_goFileDown\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)")


def find_tot_page(text: str) -> int:
    m = re.search(r"var\s+totPage\s*=\s*(\d+)", text)
    return int(m.group(1)) if m else 1


def parse_notice_list(text: str) -> list[dict]:
    tree = HTMLParser(text)
    items = []
    for a in tree.css("a.title"):
        onclick = a.attributes.get("onclick") or a.attributes.get("onClick") or ""
        m = _DTL.search(onclick)
        if not m:
            continue
        twbbs_id = m.group(1)
        title = a.text(strip=True)
        # 같은 행(tr)의 날짜 셀
        tr = a.parent
        while tr is not None and tr.tag != "tr":
            tr = tr.parent
        updated_at = None
        if tr is not None:
            dm = _DATE.search(tr.text(separator=" ", strip=True))
            updated_at = dm.group(0) if dm else None
        items.append({"twbbs_id": twbbs_id, "title": title, "updated_at": updated_at})
    return items


def parse_notice_detail(text: str) -> dict:
    tree = HTMLParser(text)
    title_node = tree.css_first(".board_view .view_bg strong") or tree.css_first(".view_bg strong")
    title = title_node.text(strip=True) if title_node else None
    body_node = tree.css_first(".board_view") or tree.body
    body_text = body_node.text(separator="\n", strip=True) if body_node else ""
    dm = _DATE.search(body_text)
    updated_at = dm.group(0) if dm else None
    # 실제 본문은 .board_view(메타) 밖의 white-space:pre-line div에 있다.
    content_text = ""
    for d in tree.css("div"):
        style = d.attributes.get("style") or ""
        if "pre-line" in style:
            content_text = d.text(separator="\n", strip=True)
            break
    # 첨부: fn_goFileDown 앵커마다 같은 <li>의 <span>에서 파일명 추출
    attachments = []
    seen = set()
    for a in tree.css("a"):
        oc = a.attributes.get("onclick") or a.attributes.get("onClick") or ""
        m = _FILE.search(oc)
        if not m:
            continue
        fm, fid = m.group(1), m.group(2)
        if not fm.startswith("FILEMSTER") or (fm, fid) in seen:
            continue
        seen.add((fm, fid))
        fname = None
        li = a.parent
        while li is not None and li.tag != "li":
            li = li.parent
        if li is not None:
            sp = li.css_first("span")
            if sp:
                fname = sp.text(strip=True) or None
        attachments.append({"file_master_id": fm, "file_id": fid, "file_name": fname})
    return {"title": title, "updated_at": updated_at, "body_text": body_text,
            "content_text": content_text, "attachments": attachments}
