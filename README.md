# douyin_download

轻量级抖音作品链接解析与详情 CLI。只做两件事：

1. 从抖音搜索页、作品页或分享文本中解析作品 ID。
2. 调用抖音网页作品详情接口，输出作品详情 JSON。

不需要 SQL、Redis、Web 服务、任务队列或浏览器。数据只在内存中处理，默认不写文件。

## 安装

需要 Python 3.11 或更高版本。

    pip install .

## 使用

解析你提供的搜索链接：

    douyin-download parse "https://www.douyin.com/root/search/美少女视频?aid=7e734c83-1c2f-4e12-91de-d71cabe7f0b3&modal_id=7349403611006389555&type=general"

查询作品详情：

    douyin-download detail "https://www.douyin.com/root/search/美少女视频?aid=7e734c83-1c2f-4e12-91de-d71cabe7f0b3&modal_id=7349403611006389555&type=general"

也可以直接传作品 ID：

    douyin-download detail 7349403611006389555

详情成功时，标准输出为详情 JSON（优先输出响应中的 aweme_detail 字段）。解析命令是离线的；详情命令需要访问抖音。

## Cookie 与风控

部分网络环境或请求会受到抖音风控限制。若访客请求返回 403 或签名相关错误，可以把自己浏览器中抖音站点的 Cookie 放入环境变量，不要提交到 Git：

    export DOUYIN_COOKIE='cookie_name=value; another_cookie=value'
    douyin-download detail 7349403611006389555

也可用 --cookie-file 指向只包含 Cookie 请求头内容的文本文件。程序只在本次运行中读取它，不会把 Cookie 或结果存入数据库。不要把含有登录态的 Cookie 分享给他人。

## 验证状态

本项目包含离线解析测试。运行详情请求需要当前网络可以连接 www.douyin.com；若返回风控或接口结构变化，CLI 会显示请求错误，而不会将“解析出了 ID”误报为“成功获取详情”。

## 实现来源

A-Bogus 与 SM3 实现来自同一账户维护的 Apache-2.0 项目 pygojrc/Douyin_TikTok_Download_API，并为本项目调整为独立模块。见 LICENSE 及 vendored 模块头部说明。

## One-off live smoke check

The GitHub Actions workflow contains a single anonymous request to the sample work. To run it on a future change, use a push commit message containing [live-smoke]. It is deliberately opt-in so routine unit tests do not depend on Douyin availability.
