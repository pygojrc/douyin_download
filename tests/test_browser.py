from __future__ import annotations

import os
import stat

import pytest

import douyin_download.browser as browser_module


def test_missing_cookie_is_fetched_and_saved(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cookie_path = tmp_path / "douyin_cookie"
    fresh_cookie = "UIFID_TEMP=visitor-123; s_v_web_id=verify-456"
    monkeypatch.setattr(browser_module, "fetch_visitor_cookie", lambda: fresh_cookie)

    actual = browser_module.load_managed_cookie(cookie_path)

    assert actual == fresh_cookie
    assert cookie_path.read_text(encoding="utf-8").strip() == fresh_cookie
    if os.name == "posix":
        assert stat.S_IMODE(cookie_path.stat().st_mode) == 0o600


def test_existing_cookie_is_reused_without_starting_browser(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    cookie_path = tmp_path / "douyin_cookie"
    cached_cookie = "UIFID_TEMP=still-valid; s_v_web_id=verify-456"
    cookie_path.write_text(cached_cookie, encoding="utf-8")

    def unexpected_browser_start() -> str:
        pytest.fail("valid cached Cookie should not start Chromium")

    monkeypatch.setattr(browser_module, "fetch_visitor_cookie", unexpected_browser_start)

    assert browser_module.load_managed_cookie(cookie_path) == cached_cookie


def test_cache_without_uifid_is_replaced(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cookie_path = tmp_path / "douyin_cookie"
    cookie_path.write_text("unrelated=value", encoding="utf-8")
    fresh_cookie = "UIFID_TEMP=new-visitor"

    monkeypatch.setattr(browser_module, "fetch_visitor_cookie", lambda: fresh_cookie)

    assert browser_module.load_managed_cookie(cookie_path) == fresh_cookie
    assert cookie_path.read_text(encoding="utf-8").strip() == fresh_cookie


def test_has_uifid_cookie_accepts_supported_spellings() -> None:
    assert browser_module.has_uifid_cookie("UIFID_TEMP=abc")
    assert browser_module.has_uifid_cookie("uifid=abc")
    assert not browser_module.has_uifid_cookie("sessionid=abc")


def test_cookie_header_from_cdp_cookies() -> None:
    header = browser_module._header_from_cdp_cookies(
        [
            {"name": "UIFID_TEMP", "value": "visitor"},
            {"name": "s_v_web_id", "value": "verify"},
            {"name": "", "value": "ignored"},
        ]
    )
    assert header == "UIFID_TEMP=visitor; s_v_web_id=verify"
