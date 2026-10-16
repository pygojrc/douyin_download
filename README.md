# douyin_download

轻量级抖音作品链接解析与详情 CLI，只做两件事：

1. 从抖音搜索页、作品页或分享文本中解析作品 ID。
2. 调用抖音网页作品详情接口，输出作品详情 JSON。

项目使用 Python CLI，不需要 SQL、Redis、Web 服务或任务队列。详情请求默认自动获取并缓存抖音访客 Cookie；链接解析本身不需要启动浏览器。

## 环境要求

- Python 3.11 或更高版本
- uv
- 本机安装 Chromium 或 Google Chrome
- 能够访问 www.douyin.com

## 安装

在项目根目录执行：

    uv sync --extra dev

如果系统未自动找到浏览器，可以指定浏览器可执行文件：

    export DOUYIN_CHROMIUM_PATH=/usr/bin/chromium

## 使用

### 解析链接

解析命令是离线操作，不会启动浏览器：

    uv run douyin-download parse "https://www.douyin.com/video/7349403611006389555"

也支持抖音搜索页面中的 modal_id、分享文本和直接传入作品 ID。

### 查询作品详情

    uv run douyin-download detail 7349403611006389555

首次执行详情请求时，如果项目根目录中还没有有效的 douyin_cookie，程序会自动启动临时 Chromium 获取访客 Cookie。获取后将 Cookie 写入缓存，并使用它继续请求作品详情。

## 自动获取与缓存 Cookie

自动获取流程已经在本机确认完成。工作逻辑如下：

1. **检查缓存：** 读取项目根目录的 douyin_cookie。缓存中有可识别的 UIFID 时直接复用，不启动浏览器。
2. **启动隔离浏览器：** 缓存不存在或不含 UIFID 时启动 Chromium，使用全新的临时 profile，不读取日常浏览器的 Cookie 或登录会话。
3. **访问抖音并读取 Cookie：** 使用 CDP 连接本次启动的浏览器。CDP 只绑定到 127.0.0.1，调试端口随机选择为非零端口。页面加载后会等待访客 Cookie 初始化。
4. **关闭和清理：** 获取成功或发生错误时都会关闭 Chromium；临时 profile 会自动清理。
5. **持久化缓存：** Cookie 通过原子替换写入项目根目录的 douyin_cookie。在支持 POSIX 文件权限的平台上，文件权限限制为仅当前用户可读写（0600）。
6. **失效刷新：** 如果详情接口明确返回 UIFID Not Found，程序会重新获取 Cookie、覆盖缓存并将详情请求重试一次。第二次仍失败时返回错误，不会循环启动浏览器。

本机有图形桌面时，默认使用普通可见的 Chromium 窗口；没有图形桌面时才默认使用无头模式。浏览器窗口是独立访客会话，不会复用已有的浏览器登录状态。

缓存文件可能包含可复用的访客标识，因此已加入 .gitignore。请勿将 douyin_cookie 提交到版本控制、上传到公开位置或分享给他人。删除该文件后再次运行详情命令，可以强制重新获取访客 Cookie。

## Cookie 选项

通常不需要手动处理 Cookie。以下选项适用于需要显式控制的场景。

### 指定 Cookie 文件

    uv run douyin-download detail 7349403611006389555 --cookie-file ./my_cookie.txt

文件内容应为 HTTP Cookie 请求头格式，例如：

    UIFID_TEMP=...; s_v_web_id=...

### 通过环境变量传入

    export DOUYIN_COOKIE='UIFID_TEMP=...; s_v_web_id=...'
    uv run douyin-download detail 7349403611006389555

显式传入的 DOUYIN_COOKIE 优先于自动缓存。设置了 --cookie-file 时则使用指定文件。

### 禁用自动启动浏览器

    uv run douyin-download detail 7349403611006389555 --no-auto-browser

该选项只使用显式传入的 --cookie-file 或 DOUYIN_COOKIE，适合 CI、匿名烟测或不希望启动浏览器的场景。

### 控制浏览器模式

本机有图形桌面时默认使用普通窗口；在没有图形桌面的环境中默认使用无头模式。如需显式控制：

    DOUYIN_CHROMIUM_HEADLESS=1 uv run douyin-download detail 7349403611006389555

将该变量设置为 0 可要求使用普通窗口；此模式需要可用的图形桌面。

详情命令还支持 --timeout 设置详情 HTTP 请求的超时时间，例如：

    uv run douyin-download detail 7349403611006389555 --timeout 30

## 故障排查

### 未取得 UIFID

如果出现“未取得 UIFID 访客 Cookie”，说明浏览器拿到的 Cookie 中没有 UIFID_TEMP 或兼容的 UIFID 字段。这与 A-Bogus 签名无关：UIFID 是抖音向浏览器访客会话下发的标识，无法通过伪造 s_v_web_id 或随便生成一个 UIFID 来替代。

可以检查当前机器是否能够正常访问抖音首页；在桌面环境运行时，观察打开的 Chromium 是否加载完成。如果抖音没有为当前访客会话下发 UIFID，或网络/风控阻止了下发，程序会报告错误，而不是伪造 Cookie。

### UIFID Not Found

详情接口明确拒绝缓存的 UIFID 时，程序会自动更新缓存并重试一次。若重试仍失败，请确认抖音首页可以正常加载，或手动传入自己已经取得的有效访客 Cookie。

### 其他 403、签名错误或没有详情内容

其他风控、签名、作品可见性错误不一定表示 Cookie 失效，因此不会自动反复启动浏览器。离线解析成功也不代表抖音一定允许实时详情请求；详情功能始终依赖当前网络和上游接口策略。

## 测试

运行离线和单元测试：

    uv run pytest -q

GitHub Actions 中的 [live-smoke] 烟测通过 --no-auto-browser 明确禁用自动浏览器获取，因此测试的是匿名详情接口，不依赖 CI runner 安装 Chromium。

## 实现来源与许可

A-Bogus 与 SM3 实现来自同一账户维护的 Apache-2.0 项目 pygojrc/Douyin_TikTok_Download_API，并为本项目调整为独立模块。详情见 LICENSE 和 THIRD_PARTY_NOTICES.md。
