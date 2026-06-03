# jforest/parsers/policies.py
import json
import re

from selectolax.parser import HTMLParser


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
    body = tree.body
    raw = body.text(separator="\n", strip=True) if body else ""
    cleaned = re.sub(r"\n{2,}", "\n", raw)
    return cleaned[:8000]
