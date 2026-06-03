# jforest/parsers/rooms.py
import re

from selectolax.parser import HTMLParser


def parse_room_list(text: str) -> list[dict]:
    tree = HTMLParser(text)
    rooms = []
    for tr in tree.css("tr.mapListTr"):
        tr_id = tr.attributes.get("id") or ""
        m = re.search(r"GID[0-9A-Za-z]+", tr_id)
        if not m:
            inner = tr.html or ""
            m = re.search(r"goodsId=(GID[0-9A-Za-z]+)", inner)
        if not m:
            continue
        goods_id = m.group(0).replace("goodsId=", "")
        tds = tr.css("td")
        room_type = tds[0].text(strip=True) if len(tds) > 0 else None
        name = tds[1].text(strip=True) if len(tds) > 1 else None
        capacity_area = tds[2].text(strip=True) if len(tds) > 2 else ""
        cap_m = re.search(r"(\d+)\s*인", capacity_area)
        area_m = re.search(r"([\d.]+\s*㎡)", capacity_area)
        rooms.append({
            "goods_id": goods_id,
            "room_type": room_type,
            "name": name,
            "capacity_standard": None,  # 목록에는 없음. 상세에서 보강
            "capacity_max": int(cap_m.group(1)) if cap_m else None,
            "area": area_m.group(1) if area_m else (capacity_area or None),
        })
    return rooms
