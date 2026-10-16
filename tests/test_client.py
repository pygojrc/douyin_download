from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

import douyin_download.client as client_module
from douyin_download.client import DetailRequestError, _url_and_headers


def test_detail_url_includes_work_id_and_a_bogus() -> None:
    url, _headers = _url_and_headers(
        "7349403611006389555",
        "https://www.douyin.com/video/7349403611006389555",
        None,
    )
    query = parse_qs(urlsplit(url).query)
    assert query["aweme_id"] == ["7349403611006389555"]
    assert query["a_bogus"]


def test_uifid_cookie_adds_web_signature() -> None:
    url, headers = _url_and_headers(
        "7349403611006389555",
        "https://www.douyin.com/video/7349403611006389555",
        "UIFID_TEMP=test-visitor-id; s_v_web_id=verify-fp-test",
    )
    query = parse_qs(urlsplit(url).query)
    assert query["uifid"] == ["test-visitor-id"]
    assert query["verifyFp"] == ["verify-fp-test"]
    assert query["fp"] == ["verify-fp-test"]
    assert query["x-secsdk-web-signature"]
    assert headers["uifid"] == "test-visitor-id"
    assert headers["x-secsdk-web-expire"]


def test_uifid_block_is_reported_with_actionable_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 403
        text = "Blocked by ArgusSecurityPlugin Uifid Not Found"

        def json(self) -> dict:
            raise ValueError("not JSON")

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    monkeypatch.setattr(client_module.httpx, "Client", FakeClient)

    with pytest.raises(DetailRequestError, match="UIFID Cookie") as error:
        client_module.fetch_detail("7349403611006389555")

    assert "DOUYIN_COOKIE" in str(error.value)
    assert "--cookie-file" in str(error.value)
