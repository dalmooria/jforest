# jforest/parsers/discounts.py
import json

from selectolax.parser import HTMLParser


def _rates(cells: list[str]) -> str:
    keys = ["off_weekday", "off_weekend", "peak_weekday", "peak_weekend"]
    return json.dumps(dict(zip(keys, cells)), ensure_ascii=False)


def parse_discounts(text: str) -> list[dict]:
    tree = HTMLParser(text)
    rows = []
    for tr in tree.css("tbody tr"):
        th = tr.css_first("th")
        tds = [td.text(separator=" ", strip=True).replace("\xa0", " ") for td in tr.css("td")]
        if not th or len(tds) < 15:
            continue
        target = th.text(strip=True).replace("\xa0", " ")
        rows.append({
            "target": target,
            "category": tds[0],
            "timing": tds[1],
            "apply_date": tds[2],
            "room_rates": _rates(tds[3:7]),
            "campsite_rate": _rates(tds[7:11]),
            "facility_rate": _rates(tds[11:15]),
        })
    return rows
