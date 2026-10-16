"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

from .browser import (
    BrowserCookieError,
    cookie_file_path,
    load_managed_cookie,
    refresh_cookie_file,
)
from .client import (
    CookieRejectedError,
    DetailRequestError,
    _load_cookie,
    fetch_detail,
)
from .links import LinkError, expand_short_link, parse_link


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="douyin-download",
        description="解析抖音作品链接或请求作品详情，不使用数据库和 Redis。",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    parse_cmd = sub.add_parser("parse", help="离线解析链接并输出作品 ID")
    parse_cmd.add_argument("value", help="抖音 URL、分享文本或作品 ID")
    parse_cmd.add_argument("--expand", action="store_true", help="对短链接执行网络重定向解析")
    detail_cmd = sub.add_parser("detail", help="请求并输出作品详情 JSON")
    detail_cmd.add_argument("value", help="抖音 URL、分享文本或作品 ID")
    detail_cmd.add_argument("--cookie-file", help="手动指定纯文本 Cookie 请求头文件")
    detail_cmd.add_argument("--timeout", type=float, default=20.0, help="HTTP 超时秒数，默认 20")
    detail_cmd.add_argument(
        "--no-auto-browser",
        action="store_true",
        help="不自动启动 Chromium；只使用 --cookie-file 或 DOUYIN_COOKIE",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "parse":
            info = parse_link(args.value)
            if args.expand and info.needs_expansion:
                info = parse_link(expand_short_link(info.original_url))
            print(json.dumps(info.to_dict(), ensure_ascii=False, indent=2))
            return 0

        use_managed_cookie = (
            not args.no_auto_browser
            and not args.cookie_file
            and not os.environ.get("DOUYIN_COOKIE")
        )
        managed_path = cookie_file_path() if use_managed_cookie else None
        cookie = (
            load_managed_cookie(managed_path)
            if managed_path is not None
            else _load_cookie(args.cookie_file)
        )

        try:
            detail = fetch_detail(args.value, cookie_header=cookie, timeout=args.timeout)
        except CookieRejectedError:
            if managed_path is None:
                raise
            print(
                "提示：缓存的 UIFID Cookie 已被抖音拒绝，正在通过临时 Chromium 重新获取。",
                file=sys.stderr,
            )
            cookie = refresh_cookie_file(managed_path)
            # Intentionally retry once only. A second rejection is returned to the caller.
            detail = fetch_detail(args.value, cookie_header=cookie, timeout=args.timeout)

        print(json.dumps(detail, ensure_ascii=False, indent=2))
        return 0
    except (
        LinkError,
        DetailRequestError,
        BrowserCookieError,
        httpx.HTTPError,
        OSError,
    ) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
