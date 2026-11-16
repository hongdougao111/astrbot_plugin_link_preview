# 链接解析 · astrbot_plugin_link_preview

聊天里丢个链接，它自己把标题、站点、简介和封面图拼成一条消息回出来。

## 指令只有两个

| 指令 | 作用 |
| --- | --- |
| `/解析` | 看这个会话现在是开还是关 |
| `/解析 开` / `/解析 关` | 打开 / 关掉这个会话的自动解析 |

没有 `/下载`，也不用发指令——**发链接就自动下**。B 站视频下来直接发群里，其他链接回标题加封面。

开关是按会话记的：群 A 关了不影响群 B。状态存在
`data/plugin_data/astrbot_plugin_link_preview/state.json`，重启不丢。

只有管理员能改，普通群友发 `/解析 关` 不生效。

## 用起来

装进 `data/plugins/` 之后重载插件就行，默认就开着。

- 群里有人发 `https://github.com/AstrBotDevs/AstrBot` → 回一条带封面和简介的卡片
- `/解析 <url>` → 手动解析一个，不写 url 就用这条消息里的第一个链接
- `/解析开关` → 管理员看当前状态

## 配置项

WebUI 插件配置页里改，或者直接编辑 `data/config/astrbot_plugin_link_preview_config.json`。

| 键 | 说明 |
| --- | --- |
| `enabled` | 总开关，关掉之后普通消息不解析，指令还能用 |
| `whitelist` | 域名白名单，留空 = 全解析；填了就只认这些及其子域 |
| `blacklist` | 域名黑名单，优先级高于白名单 |
| `max_links` | 一条消息最多解析几个 |
| `cooldown` | 同会话冷却秒数，0 = 不冷却 |
| `stop_llm` | 打开后带链接的消息只回解析结果，不再走 AI |
| `send_image` | 要不要带封面图 |
| `extra_headers` | 额外请求头，需要 Cookie 的站点在这里补 |
| `insecure_ssl` | 跳过证书校验。机器缺 CA 库时报 CERTIFICATE_VERIFY_FAILED 才打开 |

## 实现上几个值得说的点

**只读 head。** 边收边找 `</head>`，找到就断流，再按 `max_html_kb` 兜一个上限。一个 200MB 的视频页也不会把内存吃穿。

**封面图落盘。** 直接把远端的图片 URL 交给平台，十有八九被防盗链拦掉。这里先下到 `data/plugin_data/astrbot_plugin_link_preview/img_cache/`，按 URL 的 SHA1 命名，七天过期，`_prune_cache` 顺手清。写文件走 `.part` 再 rename，避免半个文件被当缓存命中。

**不用 `filter.regex`。** 那是抢占式的，会把别的插件的正则消息一起吃掉。这里用 `event_message_type(ALL)` 自己扫文本，看完不 `stop_event()` 就当没发生。

**不会自己回自己。** 校验 `sender_id == self_id`，否则解析结果里带的链接又会被自己抓到，直接自激。

**异常全吞在内部。** 一个坏链接只写一条 debug 日志，`silent_on_fail` 开着连提示都不发。


## 平台专用解析

通用 meta 抓不到的东西，走专用接口。命中域名就走，拿不到自动回落通用 meta。

| 平台 | 命中域名 | 数据来源 | 状态 |
| --- | --- | --- | --- |
| 哔哩哔哩 | bilibili.com / b23.tv / bili2233.cn | 官方 `x/web-interface/view` 接口 | 可用，实测通过 |
| 网易云音乐 | music.163.com / 163cn.tv | 官方 `api/song/detail` 接口 | 可用，实测通过 |
| 抖音 | douyin.com / v.douyin.com / iesdouyin.com | 分享页 `_ROUTER_DATA` | 需要 Cookie，见下 |

### 抖音这一块得说清楚

无 Cookie 请求分享页，返回的 `_ROUTER_DATA` 里只有页面壳，
`videoInfoRes.item_list` 是空的。换 PC UA 直接吐 `验证码中间页`。
旧接口 `/web/api/v2/aweme/iteminfo/` 现在返回空 body，
`/aweme/v1/web/aweme/detail/` 直接 `403 Blocked by ArgusSecurityPlugin`。

插件不做签名算法。那东西跟着抖音前端版本变，写死在插件里过两周就废，
维护成本比功能本身高。**配置里有个 `douyin_cookie`，贴一条你自己浏览器的
Cookie 进去就能解析**。不填也能装，只是抖音链接会返回空，静默跳过。

拿 Cookie：浏览器打开 douyin.com 并登录 → F12 → Network → 随便点一个请求 →
Request Headers 里复制整条 `Cookie` 的值。

Cookie 失效了会退化成解析不出来，重新复制一条就行。

### 加新平台

`resolvers.py` 里写一个 `async def resolve_xxx(session, url) -> Preview | None`，
再往 `RESOLVERS` 列表里加一行 `(匹配函数, 处理函数)`。
不用改 main.py。


## 下载视频发群里

打开 `download_video` 之后，B 站链接不再只发预览，而是把视频下下来直接发出去。

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `download_video` | 关 | 总开关 |
| `max_video_mb` | 50 | 超过就不下，回退成普通预览 |
| `video_quality` | 480P | 360P / 480P / 720P。不带 Cookie 最高 720P |

也可以手动触发：`/下载 https://www.bilibili.com/video/BVxxxx`。

**实现上几点**

走 `x/player/playurl` 的 `fnval=1`，拿的是 `durl` 合并流——
音视频已经并好，一个 mp4 直接能发。`fnval=16` 是 dash 分离流，还得自己合流，
群里发不出去，所以没用。

下载是流式的，`iter_chunked(65536)` 边收边写，边数着字节数，
超过 `max_video_mb` 立刻中止并删掉半个文件，不会把磁盘写满。
先写 `.part` 再 rename，避免下到一半的文件被当成缓存命中。

缓存键用 `bvid + 清晰度`，不是 URL。B 站直链每次都带不同的签名参数，
拿 URL 做 key 会导致同一个视频反复下载。实测第二次命中缓存，耗时从 12.6s 降到 0.3s。

**只有 B 站能下**。网易云的音频接口 `song/enhance/player/url` 现在对无 Cookie
请求返回 `code:-110`（版权限制），`song/media/outer/url` 直接 404。
抖音要 Cookie 加签名。这两个都没做，别指望。

## 自测

不用装 AstrBot：

```bash
python tests/test_local.py
```

给 `astrbot.*` 打了桩，验证 meta 解析、`</head>` 截断、域名匹配、URL 提取、冷却。

## 已知边界

- 只认 `<meta>` 和 `<title>`。SPA 那种首屏没有 meta 的站点解析不出来，需要针对性适配。
- 不做 JS 渲染。
- B 站 / 微博这类需要走 API 的站点不在范围内，只出通用 meta。

## 发版

版本号只有一个来源：`metadata.yaml` 的 `version`。tag 必须跟它对齐。

```bash
python scripts/check_version.py           # 只看 metadata 合不合法
python scripts/check_version.py v1.1.0    # 和指定 tag 对比
python scripts/check_version.py --bump patch   # 1.0.0 -> 1.0.1
```

一键发版：

```bash
python scripts/release.py 1.1.0
```

依次做：校验版本 → 检查工作区干净 → 打包 → 打 tag → 推送 → 建 Release。
加 `--no-push` 只打包打 tag 不推。

**为什么不用 git hook**：这台机器的 git for Windows 起不了 sh，
报 `couldn't create signal pipe, Win32 error 5`，任何 shell 钩子都跑不起来。
所以校验放进 `release.py`，发版必经此路。手动 `git push` 绕过去它管不着。

### 找 gh / git 的顺序

脚本里不写死路径，依次看三个来源：

1. 命令行 `--gh <path>` / `--git <path>`
2. 环境变量 `GH_PATH` / `GIT_PATH`
3. `PATH`

三个都没有就报错，让你自己去配，不猜。

```bash
# 环境变量方式（当前会话有效）
export GH_PATH="E:/Apps/GitHub CLI/bin/gh.exe"
python scripts/release.py 1.1.0

# 或者每次显式给
python scripts/release.py 1.1.0 --gh "E:/Apps/GitHub CLI/bin/gh.exe"
```

`owner/repo` 也从 `origin` 的 URL 里推，https 和 ssh 两种写法都认，不写死仓库名。

### 为什么 gh 老是「不能用」

这台机器上：

- 用户 PATH 里有个 `D:\dsh-tools\gh`，是**空目录**，而且不可写（指向不存在的卷）
- 真正的 gh.exe 在 `E:\Apps\GitHub CLI\bin\`，这个目录不在任何 PATH 里
- `gh` 的注册表项写不进去（`Requested registry access is not allowed`），所以改不了用户 PATH

结果：`which gh` 永远找不到，但 gh 本身是好的（`gh auth status` 正常，账号 hongdougao111，
token 带 repo 权限）。**不是 gh 坏了，是 PATH 里那条是死路。**

每次开新窗口设一次：

```bat
scripts\\setup_env.bat
```

或者自己设：

```bat
set GH_PATH=E:\Apps\GitHub CLI\bin\gh.exe
set GIT_PATH=C:\Users\<你>\PortableGit\cmd\git.exe
```

**GIT_PATH 那行为什么也要**：PATH 里的 git 是 dsh 自带的
（`dsh-ops/shells/.../winuxcmd/usr/bin/git.exe`），它的 schannel 后端推 GitHub 报
`SEC_E_NO_CREDENTIALS`。PortableGit 那个配 openssl 后端能用。

### 视频为什么分两条消息发

OneBot v11 对 video 段有硬约束，协议端直接返回：

```
retcode=1400
wording='message element "video" must be the only segment in a message'
```

所以带文字的 video 消息整条会被拒，插件这边看起来「发了」其实没发出去。
现在的做法是文字一条、视频一条：

```
消息1: [Plain]   【标题】UP主 · 时长 / 链接 / 文件 10 MB
消息2: [Video]   视频本体
```

配置里 `video_send_mode` 可以切成 `file`，改成发群文件，
某些协议端更稳，但群里会显示成附件而不是能直接播放的视频。