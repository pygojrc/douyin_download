"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from .client import DetailRequestError, _load_cookie, fetch_detail
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
    detail_cmd.add_argument("--cookie-file", help="纯文本 Cookie 请求头文件（可选）")
    detail_cmd.add_argument("--timeout", type=float, default=20.0, help="HTTP 超时秒数，默认 20")
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
        cookie = _load_cookie(args.cookie_file)
        detail = fetch_detail(args.value, cookie_header=cookie, timeout=args.timeout)
        print(json.dumps(detail, ensure_ascii=False, indent=2))
        return 0
    except (LinkError, DetailRequestError, httpx.HTTPError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
