from douyin_download.links import LinkError, parse_link


SEARCH_URL = (
    "https://www.douyin.com/root/search/%E7%BE%8E%E5%B0%91%E5%A5%B3%E8%A7%86%E9%A2%91"
    "?aid=7e734c83-1c2f-4e12-91de-d71cabe7f0b3"
    "&modal_id=7349403611006389555&type=general"
)


def test_parse_search_link_from_prompt():
    parsed = parse_link(SEARCH_URL)
    assert parsed.platform == "douyin"
    assert parsed.resource == "work"
    assert parsed.aweme_id == "7349403611006389555"
    assert parsed.canonical_url == "https://www.douyin.com/video/7349403611006389555"


def test_parse_escaped_ampersands():
    parsed = parse_link(SEARCH_URL.replace("&", "\\&"))
    assert parsed.aweme_id == "7349403611006389555"


def test_parse_video_path():
    assert parse_link("https://www.douyin.com/video/7349403611006389555").aweme_id == "7349403611006389555"


def test_parse_share_text():
    parsed = parse_link("复制此链接，打开抖音 https://www.douyin.com/video/7349403611006389555?from=copy")
    assert parsed.aweme_id == "7349403611006389555"


def test_reject_untrusted_host():
    try:
        parse_link("https://www.douyin.com.example.org/video/7349403611006389555")
    except LinkError:
        pass
    else:
        raise AssertionError("untrusted host was accepted")
