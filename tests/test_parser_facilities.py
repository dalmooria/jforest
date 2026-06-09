# tests/test_parser_facilities.py
from jforest.parsers.facilities import find_info_menu_urls, html_to_text

MENU = """{"menuList":[
  {"menuNm":"온라인예약","menuUrl":"/rep/or/x.do?hmpgId=ID1"},
  {"menuNm":"자연휴양림안내","menuUrl":"/pot/rm/ri/selectRcrfrIntrdDtlView.do?hmpgId=ID1&menuId=002001"},
  {"menuNm":"프로그램","menuUrl":"/pot/rm/fa/selectPrgrmListView.do?hmpgId=ID1&menuId=002003"},
  {"menuNm":"월별현황조회","menuUrl":"javascript:movePage('x')"}
]}"""


def test_find_info_menu_urls_picks_intro_and_program():
    urls = find_info_menu_urls(MENU)
    assert "selectRcrfrIntrdDtlView" in urls["intro"]
    assert "selectPrgrmListView" in urls["program"]


def test_find_info_menu_urls_handles_missing_program():
    menu = '{"menuList":[{"menuNm":"자연휴양림안내","menuUrl":"/pot/rm/ri/x.do?hmpgId=ID1"}]}'
    urls = find_info_menu_urls(menu)
    assert urls["intro"]
    assert urls["program"] is None


def test_find_info_menu_urls_skips_javascript_links():
    menu = '{"menuList":[{"menuNm":"프로그램","menuUrl":"javascript:foo()"}]}'
    assert find_info_menu_urls(menu)["program"] is None


def test_find_info_menu_urls_bad_json():
    assert find_info_menu_urls("not json") == {"intro": None, "program": None}


def test_html_to_text_strips_tags_and_scripts():
    html = "<html><body><script>var x=1;</script><h1>숲해설</h1><p>운영기간: 3월~</p></body></html>"
    text = html_to_text(html)
    assert "숲해설" in text and "운영기간" in text
    assert "var x" not in text


def test_html_to_text_prefers_content_container_over_boilerplate():
    html = (
        "<html><body>"
        "<header>로그인 회원가입 통합예약</header>"
        "<nav>지역 전체 날짜선택 인원</nav>"
        "<div id='container'><h2>휴양림소개</h2><p>맑은 계곡 물놀이 가능</p></div>"
        "<footer>대표전화 1588-3250</footer>"
        "</body></html>"
    )
    text = html_to_text(html)
    assert "물놀이" in text
    # 헤더/네비/푸터 보일러플레이트는 빠져야 한다
    assert "로그인" not in text
    assert "날짜선택" not in text
    assert "1588-3250" not in text
