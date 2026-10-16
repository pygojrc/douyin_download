"""Small synchronous client for Douyin's work-detail web endpoint."""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from urllib.parse import quote, urlencode

import httpx

from .links import LinkError, expand_short_link, parse_link
from .signing.abogus import ABogus, browser_info_from_screen
from .signing.websign import SALT as WEB_SIGN_SALT, pick_uifid

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
DETAIL_ENDPOINT = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
MS_TOKEN_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-"


class DetailRequestError(RuntimeError):
    """Network request failed, was blocked, or returned an unexpected shape."""


class CookieRejectedError(DetailRequestError):
    """Douyin explicitly reported that the visitor UIFID cookie was not accepted."""


def _uifid_rejected_message() -> str:
    return (
        "抖音拒绝了详情请求（UIFID Not Found）。当前 Cookie 无效或未被抖音识别。"
        "使用 CLI 默认的项目根目录 ./douyin_cookie 时，程序会自动重新获取访客 Cookie "
        "并重试一次；也可以通过 DOUYIN_COOKIE 环境变量或 --cookie-file 手动提供 Cookie。"
        "伪造 UIFID 无法解决此错误。"
    )


def _parse_cookie(cookie_header: str | None) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for pair in (cookie_header or "").split(";"):
        name, sep, value = pair.strip().partition("=")
        if sep and name:
            cookies[name] = value
    return cookies


def _fake_ms_token(rng: random.Random | None = None) -> str:
    rng = rng or random.SystemRandom()
    return "".join(rng.choice(MS_TOKEN_ALPHABET) for _ in range(126)) + "=="


def _base_params(aweme_id: str) -> list[tuple[str, str]]:
    # Keep insertion order stable: the signature covers the exact query string.
    return [
        ("device_platform", "webapp"),
        ("aid", "6383"),
        ("channel", "channel_pc_web"),
        ("pc_client_type", "1"),
        ("version_code", "290100"),
        ("version_name", "29.1.0"),
        ("cookie_enabled", "true"),
        ("screen_width", "1920"),
        ("screen_height", "1080"),
        ("browser_language", "zh-CN"),
        ("browser_platform", "Win32"),
        ("browser_name", "Chrome"),
        ("browser_version", "130.0.0.0"),
        ("browser_online", "true"),
        ("engine_name", "Blink"),
        ("engine_version", "130.0.0.0"),
        ("os_name", "Windows"),
        ("os_version", "10"),
        ("cpu_core_num", "12"),
        ("device_memory", "8"),
        ("platform", "PC"),
        ("downlink", "10"),
        ("effective_type", "4g"),
        ("round_trip_time", "0"),
        ("update_version_code", "170400"),
        ("aweme_id", aweme_id),
        ("msToken", _fake_ms_token()),
    ]


def _url_and_headers(
    aweme_id: str,
    referer: str,
    cookie_header: str | None,
) -> tuple[str, dict[str, str]]:
    pairs = _base_params(aweme_id)
    query_before_signature = urlencode(pairs)
    a_bogus = ABogus(
        USER_AGENT,
        browser_info=browser_info_from_screen(1920, 1080, "Win32"),
    ).get_value(query_before_signature)
    pairs.append(("a_bogus", a_bogus))

    cookies = _parse_cookie(cookie_header)
    uifid = pick_uifid(cookies)
    headers: dict[str, str] = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Referer": referer,
        "Origin": "https://www.douyin.com",
        "Cookie": cookie_header or "",
    }
    if uifid:
        verify_fp = cookies.get("s_v_web_id", "")
        if verify_fp:
            pairs.extend((("verifyFp", verify_fp), ("fp", verify_fp)))
        timestamp = str(int(time.time()))
        if not any(key == "uifid" for key, _ in pairs):
            pairs.append(("uifid", uifid))
        pairs.append(("timestamp", timestamp))
        query = "&".join(
            f"{quote(key, safe='*-._')}={quote(value, safe='*-._')}"
            for key, value in pairs
        )
        signature = hashlib.md5(
            f"{uifid}_{timestamp}_{WEB_SIGN_SALT}_{query}".encode("utf-8")
        ).hexdigest()
        pairs.append(("x-secsdk-web-signature", signature))
        headers["uifid"] = uifid
        headers["x-secsdk-web-expire"] = timestamp
    final_query = "&".join(
        f"{quote(key, safe='*-._')}={quote(value, safe='*-._')}"
        for key, value in pairs
    )
    return f"{DETAIL_ENDPOINT}?{final_query}", headers


def _load_cookie(cookie_file: str | None) -> str | None:
    if cookie_file:
        with open(cookie_file, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    return os.environ.get("DOUYIN_COOKIE")


def fetch_detail(value: str, *, cookie_header: str | None = None, timeout: float = 20.0) -> dict:
    """Return the aweme_detail object for a supported Douyin work URL or ID."""
    try:
        info = parse_link(value)
        if info.aweme_id is None and info.needs_expansion:
            final_url = expand_short_link(info.original_url)
            info = parse_link(final_url)
        if not info.aweme_id:
            raise LinkError("链接中没有找到作品 ID；短链接则可能无法解析或已失效")
    except (LinkError, httpx.HTTPError) as exc:
        raise DetailRequestError(str(exc)) from exc

    request_url, headers = _url_and_headers(
        info.aweme_id,
        info.original_url if info.original_url.startswith(("http://", "https://")) else info.canonical_url or "",
        cookie_header,
    )
    headers = {key: value for key, value in headers.items() if value or key != "Cookie"}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.get(request_url, headers=headers)
    except httpx.HTTPError as exc:
        raise DetailRequestError(f"请求抖音详情接口失败：{exc}") from exc

    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        response_text = response.text
        if "uifid not found" in response_text.lower():
            raise CookieRejectedError(_uifid_rejected_message()) from exc
        snippet = response_text[:400].replace("\n", " ")
        raise DetailRequestError(
            f"抖音返回了非 JSON 内容（HTTP {response.status_code}）：{snippet}"
        ) from exc

    payload_text = json.dumps(payload, ensure_ascii=False)
    if "uifid not found" in payload_text.lower():
        raise CookieRejectedError(_uifid_rejected_message())
    if response.status_code != 200:
        raise DetailRequestError(
            f"抖音详情接口返回 HTTP {response.status_code}：" + payload_text[:700]
        )
    if isinstance(payload, dict) and isinstance(payload.get("aweme_detail"), dict):
        return payload["aweme_detail"]

    raise DetailRequestError(
        "抖音未返回 aweme_detail（可能是风控、Cookie/签名校验失败，或作品不可见）。"
        + " 上游响应：" + payload_text[:1000]
    )
