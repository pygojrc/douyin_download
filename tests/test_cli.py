from __future__ import annotations

import pytest

import douyin_download.cli as cli_module
from douyin_download.client import CookieRejectedError


def test_detail_uses_managed_cookie_cache(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys) -> None:
    monkeypatch.delenv("DOUYIN_COOKIE", raising=False)
    cookie_path = tmp_path / "douyin_cookie"
    cookie_path.write_text("UIFID_TEMP=cached-visitor", encoding="utf-8")
    calls: list[str | None] = []

    def fake_fetch_detail(value: str, *, cookie_header: str | None, timeout: float) -> dict:
        calls.append(cookie_header)
        assert value == "7349403611006389555"
        return {"aweme_id": value}

    monkeypatch.setattr(cli_module, "cookie_file_path", lambda: cookie_path)
    monkeypatch.setattr(cli_module, "fetch_detail", fake_fetch_detail)

    assert cli_module.main(["detail", "7349403611006389555"]) == 0
    assert calls == ["UIFID_TEMP=cached-visitor"]
    assert '"aweme_id": "7349403611006389555"' in capsys.readouterr().out


def test_uifid_rejection_refreshes_cache_and_retries_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    monkeypatch.delenv("DOUYIN_COOKIE", raising=False)
    cookie_path = tmp_path / "douyin_cookie"
    cookie_path.write_text("UIFID_TEMP=stale-visitor", encoding="utf-8")
    calls: list[str | None] = []

    def fake_fetch_detail(value: str, *, cookie_header: str | None, timeout: float) -> dict:
        calls.append(cookie_header)
        if cookie_header == "UIFID_TEMP=stale-visitor":
            raise CookieRejectedError("UIFID Not Found")
        return {"aweme_id": value, "cookie_used": "fresh"}

    def fake_refresh_cookie(path) -> str:
        path.write_text("UIFID_TEMP=fresh-visitor", encoding="utf-8")
        return "UIFID_TEMP=fresh-visitor"

    monkeypatch.setattr(cli_module, "cookie_file_path", lambda: cookie_path)
    monkeypatch.setattr(cli_module, "fetch_detail", fake_fetch_detail)
    monkeypatch.setattr(cli_module, "refresh_cookie_file", fake_refresh_cookie)

    assert cli_module.main(["detail", "7349403611006389555"]) == 0
    assert calls == ["UIFID_TEMP=stale-visitor", "UIFID_TEMP=fresh-visitor"]
    assert cookie_path.read_text(encoding="utf-8") == "UIFID_TEMP=fresh-visitor"
    assert "正在通过临时 Chromium 重新获取" in capsys.readouterr().err


def test_no_auto_browser_allows_anonymous_smoke(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.delenv("DOUYIN_COOKIE", raising=False)
    monkeypatch.setattr(
        cli_module,
        "load_managed_cookie",
        lambda _path: pytest.fail("managed cookie should not be loaded"),
    )
    calls: list[str | None] = []

    def fake_fetch_detail(value: str, *, cookie_header: str | None, timeout: float) -> dict:
        calls.append(cookie_header)
        return {"aweme_id": value}

    monkeypatch.setattr(cli_module, "fetch_detail", fake_fetch_detail)

    assert cli_module.main(["detail", "7349403611006389555", "--no-auto-browser"]) == 0
    assert calls == [None]
    assert '"aweme_id": "7349403611006389555"' in capsys.readouterr().out
