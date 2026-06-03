# jforest/parsers/room_details.py
import re

from selectolax.parser import HTMLParser

_SEASON = {"비수기": "off", "성수기": "peak"}


def _int_price(s: str):
    m = re.search(r"([\d,]+)\s*원", s)
    return int(m.group(1).replace(",", "")) if m else None


def parse_room_detail(text: str) -> dict:
    tree = HTMLParser(text)
    page_text = tree.body.text(separator="\n", strip=True) if tree.body else ""

    capacity_standard = capacity_max = area = amenities = None
    for tr in tree.css("tr"):
        th = tr.css_first("th")
        td = tr.css_first("td")
        if not th or not td:
            continue
        label = th.text(strip=True)
        val = td.text(separator=" ", strip=True)
        if "인실" in label or "면적" in label:
            m1 = re.search(r"기준인원\s*[:：]?\s*(\d+)", val)
            m2 = re.search(r"최대인원\s*[:：]?\s*(\d+)", val)
            m3 = re.search(r"면적\s*[:：]?\s*([\d.]+\s*㎡)", val)
            capacity_standard = int(m1.group(1)) if m1 else capacity_standard
            capacity_max = int(m2.group(1)) if m2 else capacity_max
            area = m3.group(1) if m3 else area
        elif "편의시설" in label:
            amenities = val

    # 가격표: th(비수기/성수기, rowspan) 다음 td들이 평일/주말 요금
    prices = []
    current_season = None
    for tr in tree.css("tr"):
        th = tr.css_first("th")
        if th and th.text(strip=True) in _SEASON:
            current_season = _SEASON[th.text(strip=True)]
        for td in tr.css("td"):
            cell = td.text(strip=True)
            if "요금" not in cell or current_season is None:
                continue
            day_type = "weekday" if "평일" in cell else ("weekend" if "주말" in cell else None)
            price = _int_price(cell)
            if day_type and price is not None:
                prices.append({
                    "season": current_season, "day_type": day_type,
                    "raw_label": cell, "price": price,
                })

    # 이용안내 본문
    usage_guide = None
    for p in tree.css("p.wd_txt"):
        t = p.text(separator="\n", strip=True)
        if t:
            usage_guide = t
            break
    if not usage_guide:
        usage_guide = page_text

    ci = re.search(r"입실\s*[:：]?\s*([^\n※]+)", usage_guide or "")
    co = re.search(r"퇴실\s*[:：]?\s*([^\n※]+)", usage_guide or "")
    return {
        "capacity_standard": capacity_standard,
        "capacity_max": capacity_max,
        "area": area,
        "amenities": amenities,
        "usage_guide": usage_guide,
        "checkin_time": ci.group(1).strip() if ci else None,
        "checkout_time": co.group(1).strip() if co else None,
        "prices": prices,
    }
