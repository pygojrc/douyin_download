"""Offline parsing and allowlisted expansion for Douyin work URLs."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

URL_RE = re.compile(r"https?://[^\s<>\\"']+", re.IGNORECASE)
ID_RE = re.compile(r"(?<!\d)(\d{8,25})(?!\d)")
PATH_PATTERNS = (
    re.compile(r"/(?:video|note|photo)/(\d+)(?:/|$)", re.IGNORECASE),
    re.compile(r"/share/video/(\d+)(?:/|$)", re.IGNORECASE),
)
REDIRECT_CODES = {301, 302, 303, 307, 308}
ALLOWED_DOMAINS = ("douyin.com", "iesdouyin.com", "amemv.com")


class LinkError(ValueError):
    """Input URL is invalid or outside the supported platform domains."""


@dataclass(frozen=True, slots=True)
class LinkInfo:
    platform: str
    resource: str
    aweme_id: str | None
    original_url: str
    canonical_url: str | None
    needs_expansion: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _extract_candidate(value: str) -> str:
    text = value.strip().replace("\\&", "&").replace("&amp;", "&")
    match = URL_RE.search(text)
    if match:
        text = match.group(0)
    text = text.strip().rstrip(".,，。;；)]}>\\\"'\\")
    if not text:
        raise LinkError("没有找到可解析的链接或作品 ID")
    if ID_RE.fullmatch(text):
        return text
    if "://" not in text and re.match(r"(?i)(?:www\.)?(?:v\.)?(?:douyin\.com|iesdouyin\.com|amemv\.com)(?:/|$)", text):
        text = "https://" + text
    return text


def _check_url(url: str) -> tuple[str, str]:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError as exc:
        raise LinkError(f"无效 URL：{exc}") from exc
    if parts.scheme.lower() not in {"http", "https"}:
        raise LinkError("只支持 http/https 链接")
    if parts.username is not None or parts.password is not None:
        raise LinkError("URL 不允许包含 userinfo")
    if port not in {None, 80, 443}:
        raise LinkError("不支持非标准端口")
    if not host or not any(host == domain or host.endswith("." + domain) for domain in ALLOWED_DOMAINS):
        raise LinkError("这不是受支持的抖音链接域名")
    return host, parts.path or "/"


def parse_link(value: str) -> LinkInfo:
    """Parse an ID or URL without making any network requests."""
    candidate = _extract_candidate(value)
    if ID_RE.fullmatch(candidate):
        work_id = candidate
        canonical = f"https://www.douyin.com/video/{work_id}"
        return LinkInfo("douyin", "work", work_id, candidate, canonical)

    host, path = _check_url(candidate)
    parts = urlsplit(candidate)
    query = parse_qs(parts.query, keep_blank_values=True)
    work_id = None
    for key in ("modal_id", "aweme_id", "item_id", "video_id"):
        vals = query.get(key)
        if vals and ID_RE.fullmatch(vals[0]):
            work_id = vals[0]
            break
    if work_id is None:
        for pattern in PATH_PATTERNS:
            match = pattern.search(path)
            if match:
                work_id = match.group(1)
                break

    if work_id:
        canonical = f"https://www.douyin.com/video/{work_id}"
        return LinkInfo("douyin", "work", work_id, candidate, canonical)

    short_link = host == "v.douyin.com" or host.endswith(".v.douyin.com")
    return LinkInfo(
        "douyin",
        "short_link" if short_link else "unknown",
        None,
        candidate,
        None,
        needs_expansion=short_link,
    )


def expand_short_link(url: str, *, max_hops: int = 8, timeout: float = 12.0) -> str:
    """Follow one redirect at a time and validate every redirect destination."""
    current = url
    with httpx.Client(timeout=timeout, follow_redirects=False, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    }) as client:
        for _ in range(max_hops):
            _check_url(current)
            response = client.get(current)
            if response.status_code not in REDIRECT_CODES:
                info = parse_link(current)
                if info.aweme_id:
                    return current
                raise LinkError(f"短链接没有跳转到可识别的作品链接（HTTP {response.status_code}）")
            location = response.headers.get("location")
            if not location:
                raise LinkError("重定向响应缺少 Location")
            current = urljoin(current, location)
            _check_url(current)
            info = parse_link(current)
            if info.aweme_id:
                return current
    raise LinkError(f"短链接重定向超过限制（{max_hops} 跳）")
