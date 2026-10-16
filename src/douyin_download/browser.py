"""Acquire Douyin's visitor cookie from a short-lived, isolated Chromium session."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import websocket

from .signing.websign import pick_uifid

DOUYIN_HOME = "https://www.douyin.com/"
DEFAULT_COOKIE_FILENAME = "douyin_cookie"


class BrowserCookieError(RuntimeError):
    """Chromium could not be started or did not yield a usable visitor cookie."""


def _cookie_mapping(cookie_header: str | None) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for pair in (cookie_header or "").split(";"):
        name, sep, value = pair.strip().partition("=")
        if sep and name:
            cookies[name] = value
            cookies.setdefault(name.lower(), value)
            cookies.setdefault(name.upper(), value)
    return cookies


def has_uifid_cookie(cookie_header: str | None) -> bool:
    return bool(pick_uifid(_cookie_mapping(cookie_header)))


def _is_project_root(path: Path) -> bool:
    return (
        (path / "pyproject.toml").is_file()
        and (path / "src" / "douyin_download").is_dir()
    )


def cookie_file_path() -> Path:
    """Resolve douyin_cookie against the checkout root, falling back to cwd."""
    module_path = Path(__file__).resolve()
    for parent in module_path.parents:
        if _is_project_root(parent):
            return parent / DEFAULT_COOKIE_FILENAME

    current = Path.cwd().resolve()
    for parent in (current, *current.parents):
        if _is_project_root(parent):
            return parent / DEFAULT_COOKIE_FILENAME
    return current / DEFAULT_COOKIE_FILENAME


def _find_chromium() -> str:
    for variable in ("DOUYIN_CHROMIUM_PATH", "CHROMIUM_PATH", "CHROME_BIN"):
        configured = os.environ.get(variable)
        if not configured:
            continue
        resolved = shutil.which(configured) or (configured if Path(configured).is_file() else None)
        if resolved:
            return str(Path(resolved).resolve())
        raise BrowserCookieError(
            f"环境变量 {variable} 指定的 Chromium/Chrome 不存在：{configured}"
        )

    for executable in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "chrome",
        "brave-browser",
    ):
        found = shutil.which(executable)
        if found:
            return found

    raise BrowserCookieError(
        "未找到 Chromium/Chrome。请先安装浏览器，或通过 DOUYIN_CHROMIUM_PATH "
        "指定浏览器可执行文件路径。"
    )


def _wait_for_debug_port(profile: Path, process: subprocess.Popen[Any], timeout: float) -> int:
    active_port_file = profile / "DevToolsActivePort"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise BrowserCookieError(
                "Chromium 启动后立即退出。请检查浏览器安装、运行权限和系统依赖。"
            )
        try:
            lines = active_port_file.read_text(encoding="utf-8").splitlines()
            if lines:
                port = int(lines[0].strip())
                if 0 < port < 65536:
                    return port
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise BrowserCookieError("等待 Chromium 启动 CDP 端口超时。")


def _wait_for_page_socket(
    port: int, process: subprocess.Popen[Any], timeout: float
) -> str:
    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=1.0, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise BrowserCookieError("Chromium 在创建抖音页面前退出。")
            try:
                response = client.get(f"http://127.0.0.1:{port}/json/list")
                response.raise_for_status()
                targets = response.json()
                for target in targets:
                    if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                        return str(target["webSocketDebuggerUrl"])
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.1)
    raise BrowserCookieError("等待 Chromium 页面 CDP 连接超时。")


def _cdp_command(
    socket: websocket.WebSocket,
    command_id: int,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float = 3.0,
) -> dict[str, Any]:
    socket.settimeout(timeout)
    socket.send(json.dumps({"id": command_id, "method": method, "params": params or {}}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            message = json.loads(socket.recv())
        except websocket.WebSocketTimeoutException as exc:
            raise BrowserCookieError(f"等待 CDP 命令 {method} 响应超时。") from exc
        except (ValueError, websocket.WebSocketException) as exc:
            raise BrowserCookieError(f"CDP 连接异常：{exc}") from exc
        if message.get("id") != command_id:
            continue
        if "error" in message:
            raise BrowserCookieError(
                f"CDP 命令 {method} 失败：{message['error'].get('message', '未知错误')}"
            )
        result = message.get("result", {})
        return result if isinstance(result, dict) else {}
    raise BrowserCookieError(f"等待 CDP 命令 {method} 响应超时。")


def _header_from_cdp_cookies(cookies: list[dict[str, Any]]) -> str:
    pairs: list[str] = []
    for cookie in cookies:
        name, value = cookie.get("name"), cookie.get("value")
        if isinstance(name, str) and name and isinstance(value, str):
            pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def _stop_browser(process: subprocess.Popen[Any]) -> None:
    if os.name == "posix":
        # Kill the process group even if Chrome's main process exited first;
        # renderer/utility subprocesses may still be alive.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def fetch_visitor_cookie(*, timeout: float = 25.0) -> str:
    """Launch isolated headless Chromium and return the visitor Cookie header.

    Port 0 asks Chromium to allocate an ephemeral debugging port. The temporary
    user-data directory avoids accessing the user's normal browser profile.
    """
    binary = _find_chromium()
    with tempfile.TemporaryDirectory(prefix="douyin-chromium-") as temporary_profile:
        profile = Path(temporary_profile)
        command = [
            binary,
            "--headless=new",
            "--incognito",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--disable-extensions",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=0",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile}",
        ]
        if os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0:
            command.append("--no-sandbox")
        command.append(DOUYIN_HOME)

        popen_options: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "posix":
            popen_options["start_new_session"] = True
        elif os.name == "nt":
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            process = subprocess.Popen(command, **popen_options)
        except OSError as exc:
            raise BrowserCookieError(f"无法启动 Chromium：{exc}") from exc

        socket: websocket.WebSocket | None = None
        try:
            port = _wait_for_debug_port(profile, process, min(timeout, 10.0))
            page_socket_url = _wait_for_page_socket(port, process, min(timeout, 10.0))
            try:
                socket = websocket.create_connection(
                    page_socket_url,
                    timeout=3.0,
                    suppress_origin=True,
                )
            except websocket.WebSocketException as exc:
                raise BrowserCookieError(f"无法连接 Chromium CDP：{exc}") from exc

            _cdp_command(socket, 1, "Network.enable")
            _cdp_command(socket, 2, "Page.enable")
            _cdp_command(socket, 3, "Page.navigate", {"url": DOUYIN_HOME})

            deadline = time.monotonic() + timeout
            last_cookie_header = ""
            command_id = 4
            while time.monotonic() < deadline:
                result = _cdp_command(
                    socket,
                    command_id,
                    "Network.getCookies",
                    {"urls": [DOUYIN_HOME]},
                    timeout=min(3.0, max(0.5, deadline - time.monotonic())),
                )
                command_id += 1
                last_cookie_header = _header_from_cdp_cookies(result.get("cookies", []))
                if has_uifid_cookie(last_cookie_header):
                    return last_cookie_header
                time.sleep(0.25)

            if last_cookie_header:
                names = [
                    pair.partition("=")[0]
                    for pair in last_cookie_header.split(";")
                    if "=" in pair
                ]
                discovered = ", ".join(names[:20]) or "无"
            else:
                discovered = "无"
            raise BrowserCookieError(
                "Chromium 已访问抖音，但在等待期限内未取得 UIFID 访客 Cookie。"
                f"发现的 Cookie 名称：{discovered}。这可能是网络限制或抖音风控导致。"
            )
        finally:
            if socket is not None:
                try:
                    socket.close()
                except websocket.WebSocketException:
                    pass
            _stop_browser(process)


def save_cookie_file(path: Path, cookie_header: str) -> None:
    """Atomically persist a Cookie header with owner-only permissions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(cookie_header.strip() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def refresh_cookie_file(path: Path | None = None) -> str:
    """Fetch a new visitor Cookie header and persist it for subsequent runs."""
    path = Path(path) if path is not None else cookie_file_path()
    cookie_header = fetch_visitor_cookie()
    if not has_uifid_cookie(cookie_header):
        raise BrowserCookieError("Chromium 返回的 Cookie 不包含可识别的 UIFID。")
    save_cookie_file(path, cookie_header)
    return cookie_header


def load_managed_cookie(path: Path | None = None) -> str:
    """Reuse the project cookie cache; create or replace it only when needed."""
    path = Path(path) if path is not None else cookie_file_path()
    try:
        cached = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        cached = ""
    if cached and has_uifid_cookie(cached):
        return cached
    return refresh_cookie_file(path)


__all__ = [
    "BrowserCookieError",
    "cookie_file_path",
    "fetch_visitor_cookie",
    "has_uifid_cookie",
    "load_managed_cookie",
    "refresh_cookie_file",
    "save_cookie_file",
]
