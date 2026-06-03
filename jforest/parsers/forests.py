# jforest/parsers/forests.py
import json
import re


def parse_forest_list_json(text: str) -> list[dict]:
    data = json.loads(text)
    # 응답은 리스트이거나 {"list": [...]} 형태일 수 있다. 둘 다 수용.
    if isinstance(data, dict):
        for key in ("list", "resultList", "data", "huyangList", "insttList"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    rows = []
    for item in data:
        instt_id = item.get("insttId")
        if not instt_id:
            continue
        rows.append({
            "instt_id": instt_id,
            "name": item.get("insttNm"),
            "arcd": item.get("arcd"),
            "instt_type_code": item.get("insttTpcd"),
        })
    return rows


# 각 항목 content 문자열의 시작 마커 / 필드 정규식
_ITEM = re.compile(r'<div class="map_info" id="site\d+"')
_IID = re.compile(r'<input type="hidden" id="([A-Za-z0-9]+)">')
_NAME = re.compile(r"info_title\">.*?([^'<>+]+?)</div>", re.S)
_HOME = re.compile(r'class="info_button">.*?<a href="([^"]+)"[^>]*>\s*<span>홈페이지', re.S)


def parse_forest_list_html(text: str) -> list[dict]:
    # 항목 데이터는 <script> 안 `var positions = [ {content:'...'} ]` 배열에 있다.
    m = re.search(r"var\s+positions\s*=\s*\[(.*?)\];", text, re.S)
    region = m.group(1) if m else text
    starts = [mm.start() for mm in _ITEM.finditer(region)]
    items = []
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(region)
        block = region[s:end]
        iid_m = _IID.search(block)
        if not iid_m:
            continue
        name_m = _NAME.search(block)
        name = re.sub(r"\s+", " ", name_m.group(1)).strip() if name_m else None
        home_m = _HOME.search(block)
        tags = re.findall(r"#[가-힣A-Za-z0-9]+", block)
        items.append({
            "instt_id": iid_m.group(1),
            "name": name or None,
            "instt_type": None,            # HTML에 기관구분 라벨 없음 → 1a의 instt_type_code 사용
            "homepage_url": home_m.group(1) if home_m else None,
            "tags": json.dumps(tags, ensure_ascii=False) if tags else None,
            "summary": None,               # 이 뷰에 요약 없음
            "reservation_intake": None,    # reservation_policies로 보강
        })
    return items
