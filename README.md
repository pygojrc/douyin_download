# douyin_download

轻量级抖音作品链接解析与详情 CLI。只做两件事：

1. 从抖音搜索页、作品页或分享文本中解析作品 ID。
2. 调用抖音网页作品详情接口，输出作品详情 JSON。

不需要 SQL、Redis、Web 服务或任务队列。默认情况下，详情命令会使用一次性 Chromium 访客会话取得 UIFID Cookie，并缓存到项目根目录的 douyin_cookie 文件，后续重复使用；不会访问用户日常浏览器的配置文件或登录会话。

## 安装

需要 Python 3.11 或更高版本，以及本机已安装 Chromium 或 Chrome。使用 uv：

    uv sync --extra dev

也可以安装为 Python 包：

    pip install .

如果系统没有自动检测到浏览器，可通过 DOUYIN_CHROMIUM_PATH 指定可执行文件路径，例如：

    export DOUYIN_CHROMIUM_PATH=/usr/bin/chromium

## 使用

解析链接是离线操作：

    uv run douyin-download parse "https://www.douyin.com/video/7349403611006389555"

查询作品详情：

    uv run douyin-download detail 7349403611006389555

第一次运行时，如果项目根目录还没有有效的 douyin_cookie，程序会启动隔离 Chromium 并访问抖音首页。在有图形桌面的本机上，默认打开普通浏览器窗口；无图形桌面时才回退到无头模式。浏览器使用临时 profile 和随机选择的非零 CDP 端口，不读取你日常浏览器的配置。获取 Cookie 后立即关闭浏览器，并删除临时 profile。Cookie 会以当前用户可读写的权限写入项目根目录的 douyin_cookie 文件。后续请求自动读取这个文件，不会每次都启动浏览器。

当详情接口明确返回 UIFID Not Found 时，程序会重新获取 Cookie、覆盖缓存文件并重试一次。如果新的 Cookie 仍被拒绝，会报告错误并停止，不会无限循环启动浏览器。

## Cookie 优先级与管理

- 默认方式：自动读取或生成项目根目录的 douyin_cookie 文件。
- 手动文件：使用 --cookie-file 指定 Cookie 请求头文件。
- 环境变量：设置 DOUYIN_COOKIE 后使用该值，优先于自动缓存。
- 禁用浏览器：使用 --no-auto-browser，只使用显式的 --cookie-file 或 DOUYIN_COOKIE；适合匿名烟测或不希望启动浏览器的环境。

例如：

    uv run douyin-download detail 7349403611006389555 --cookie-file ./my_cookie.txt

    DOUYIN_COOKIE='UIFID_TEMP=...' uv run douyin-download detail 7349403611006389555

    uv run douyin-download detail 7349403611006389555 --no-auto-browser

douyin_cookie 包含可复用的访客 Cookie，已加入 .gitignore。请勿上传、分享或提交此文件。程序使用原子替换写入文件，并限制文件权限为仅当前用户可读写（POSIX 文件权限 0600）。要强制获取新 Cookie，可删除该文件后再次执行详情命令。

## 限制

- 本机必须安装 Chromium/Chrome，且能够访问抖音首页。临时 profile 仅用于生成访客身份，不会读取你日常浏览器的登录会话。
- 如果抖音没有签发 UIFID Cookie，或网络/风控继续拒绝请求，自动刷新也无法保证详情请求成功。Chrome 的无头模式与 CDP 端口 0 会暴露自动化状态，因此本机有桌面时默认使用普通窗口与非零随机端口；这能避免这两项特征，但不保证绕过抖音的其他风控。若要强制无头模式，可设置 DOUYIN_CHROMIUM_HEADLESS=1。
- 自动刷新仅由明确的 UIFID Not Found 错误触发；其他风控、签名或作品可见性错误不会导致反复启动浏览器。
- 项目不使用 SQL、Redis 或后台服务，作品详情仅通过标准输出返回。

## 验证状态

本项目包含离线解析、签名和 Cookie 缓存测试。详情请求仍依赖当前网络和抖音接口行为；离线测试通过不代表上游一定允许实时详情请求。

## 实现来源

A-Bogus 与 SM3 实现来自同一账户维护的 Apache-2.0 项目 pygojrc/Douyin_TikTok_Download_API，并为本项目调整为独立模块。见 LICENSE 及 vendored 模块头部说明。

## One-off live smoke check

The GitHub Actions workflow contains a single anonymous request to the sample work. To run it on a future change, use a push commit message containing [live-smoke]. The smoke test passes --no-auto-browser intentionally, so it tests the direct anonymous endpoint without requiring a Chromium install.

