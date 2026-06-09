# jforest/parsers/policies.py
import json
import re
from urllib.parse import parse_qs, urlparse

from selectolax.parser import HTMLParser

POLICY_DETAIL_TITLES = {
    "100": "예약안내정책",
    "101": "선착순 예약정책",
    "102": "주말추첨제 예약정책",
    "103": "성수기추첨제 예약정책",
    "104": "지역주민우대추첨제 예약정책",
    "105": "지역주민우선예약정책",
    "106": "실버전용우선예약정책",
    "107": "바우처우선예약정책",
    "108": "장애인우선예약정책",
    "111": "월추첨제 예약정책",
    "112": "월추첨제 예약정책",
    "211": "다자녀우선예약정책",
}


def _flag(text: str) -> int:
    t = (text or "").strip()
    return 1 if any(k in t for k in ("O", "o", "○", "●", "ㅇ", "운영", "가능")) else 0


def _has(text: str) -> bool:
    return bool((text or "").strip())


def _tokens(text: str):
    parts = [p.strip() for p in re.split(r"[,/·]", text or "") if p.strip()]
    return parts


def parse_policy_all(text: str) -> list[dict]:
    tree = HTMLParser(text)
    rows = []
    for tr in tree.css("tbody tr"):
        cells = [c.text(separator=" ", strip=True).replace("\xa0", " ") for c in tr.css("th, td")]
        # 휴양림명 셀을 앵커로 찾는다 (헤더 라벨 '휴양림' 단독은 제외)
        j = next((i for i, c in enumerate(cells)
                  if "휴양림" in c and c.strip() != "휴양림"), None)
        if j is None or len(cells) < j + 8:
            continue
        lottery = _tokens(cells[j + 6])
        priority = _tokens(cells[j + 7])
        if _has(cells[j + 4]):
            fcfs = "6주 수요일"
        elif _has(cells[j + 5]):
            fcfs = "익월말"
        else:
            fcfs = None
        rows.append({
            "name": cells[j],
            "operates_rooms": _flag(cells[j + 1]),
            "operates_campsite": _flag(cells[j + 2]),
            "operates_waitlist": _flag(cells[j + 3]),
            "fcfs_method": fcfs,
            "lottery_types": json.dumps(lottery, ensure_ascii=False) if lottery else None,
            "priority_types": json.dumps(priority, ensure_ascii=False) if priority else None,
        })
    return rows


def parse_policy_detail(text: str) -> str:
    tree = HTMLParser(text)
    for tag in tree.css("script, style"):
        tag.decompose()
    detail = tree.css_first(".wd_txt")
    body = detail or tree.body
    raw = body.text(separator="\n", strip=True) if body else ""
    cleaned = re.sub(r"\n{2,}", "\n", raw)
    return cleaned[:8000]


def parse_policy_detail_title(text: str) -> str | None:
    tree = HTMLParser(text)
    for node in tree.css("h3"):
        title = node.text(separator=" ", strip=True)
        if title and "예약정책" in title:
            return title
    for node in tree.css("a.on"):
        title = node.text(separator=" ", strip=True)
        if title and "예약정책" in title:
            return title
    return None


def policy_detail_title_or_default(rule_id: str, title: str | None = None) -> str | None:
    return title or POLICY_DETAIL_TITLES.get(str(rule_id))


def parse_policy_detail_menus(text: str) -> list[dict]:
    tree = HTMLParser(text)
    out = []
    seen = set()
    for a in tree.css("a"):
        href = a.attributes.get("href") or ""
        if "selectRsrvtGdncView.do" not in href:
            continue
        query = parse_qs(urlparse(href.replace("&amp;", "&")).query)
        rule_id = (query.get("ruleId") or [None])[0]
        menu_id = (query.get("menuId") or [None])[0]
        if not rule_id:
            continue
        key = (rule_id, menu_id)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "rule_id": rule_id,
            "menu_id": menu_id,
            "title": a.text(separator=" ", strip=True) or None,
        })
    return out
