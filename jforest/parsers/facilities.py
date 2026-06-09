# jforest/parsers/facilities.py
"""휴양림 미니홈페이지의 메뉴/정보페이지 파싱 헬퍼.

- find_info_menu_urls: selectMenuList.do JSON에서 '자연휴양림안내'(소개)·'프로그램' URL을 찾는다.
- html_to_text: 정보페이지 HTML을 LLM 입력용 평문으로 변환한다.
"""
import json

from selectolax.parser import HTMLParser

# 메뉴명 부분일치 토큰. 휴양림마다 "붉은오름자연휴양림안내", "목공체험 프로그램"처럼
# 이름이 붙으므로 부분일치로 찾는다. 단, "예약안내/이용안내/시설이용안내"는 소개가 아니다.
_INTRO_TOKEN = "휴양림안내"
_INTRO_EXTRA = ("시설안내",)
_PROGRAM_TOKEN = "프로그램"
# 소개 URL은 이 엔드포인트여야 한다(이용안내 등 오탐 방지).
_INTRO_URL_HINT = "selectRcrfrIntrdDtlView"
_PROGRAM_URL_HINT = "selectPrgrmListView"


def _is_intro(name: str, url: str) -> bool:
    if _INTRO_URL_HINT in url:
        return True
    return _INTRO_TOKEN in name or name in _INTRO_EXTRA


def _is_program(name: str, url: str) -> bool:
    return _PROGRAM_URL_HINT in url or _PROGRAM_TOKEN in name


def find_info_menu_urls(menu_json: str) -> dict:
    """메뉴 JSON에서 소개/프로그램 페이지 URL을 dict로 돌려준다.

    반환: {"intro": url|None, "program": url|None}
    """
    out = {"intro": None, "program": None}
    try:
        items = json.loads(menu_json).get("menuList", [])
    except (json.JSONDecodeError, AttributeError):
        return out
    for it in items:
        name = (it.get("menuNm") or "").strip()
        url = it.get("menuUrl") or ""
        if not url or url.startswith("javascript:"):
            continue
        if out["intro"] is None and _is_intro(name, url):
            out["intro"] = url
        elif out["program"] is None and _is_program(name, url):
            out["program"] = url
    return out


# 숲나들e 정보페이지의 본문 컨테이너(헤더/녹색예약바/메뉴/푸터를 제외).
_CONTENT_SELECTORS = ("#container", "#contents", "#content", "main")
# 본문 안에 남는 비콘텐츠 영역(빵부스러기/탭메뉴/관심버튼 등)
_DROP_SELECTORS = ("nav", "header", "footer", ".location", ".breadcrumb", ".lnb", ".gnb")


def html_to_text(html: str) -> str:
    """정보페이지 HTML에서 본문 평문만 추출한다.

    헤더/예약바/네비/푸터 같은 보일러플레이트를 빼기 위해 본문 컨테이너(#container 등)를
    우선 선택하고, 없으면 body로 폴백한다.
    """
    if not html:
        return ""
    tree = HTMLParser(html)
    for tag in tree.css("script, style"):
        tag.decompose()
    root = None
    for sel in _CONTENT_SELECTORS:
        node = tree.css_first(sel)
        if node:
            root = node
            break
    if root is None:
        root = tree.body or tree.root
    if root is None:
        return ""
    for sel in _DROP_SELECTORS:
        for tag in root.css(sel):
            tag.decompose()
    text = root.text(separator=" ", strip=True)
    return " ".join(text.split())
