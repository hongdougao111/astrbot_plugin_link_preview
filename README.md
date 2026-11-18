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
抖音整个去掉了：无 Cookie 拿不到数据，做签名算法又跟不上它前端改版，留着一个必然失败的解析器没意义。


## 点歌

```
/点 起风了
/点 周杰伦
```

歌名和歌手都行。搜到之后挑第一条能直接播的，回一条歌词信息 + 一条语音。

**能播的判定**：网易云的老外链接口
`music.163.com/song/media/outer/url?id=<id>` 能播的歌直接 302 到音频文件，
不能播的重定向到 404 页面。用 `Content-Type` 是不是 `audio/*` 来判断，不靠猜。

**为什么只挑能播的**：网易云大部分热门歌是 VIP 或者版权受限，实测搜 8 条能播 1-2 条。
所以搜 8 条全探一遍（`asyncio.gather` 并行），挑第一条能播的。
一条都不行就直说，不装作发了。

**音频格式**：OneBot 的 record 段只认 wav 和 silk，但 NapCat / Lagrange 这些协议端
对 mp3 也能吃。这里优先发 mp3（省流量），发不出去退回文件。音频同样独占一条消息。


## 小程序 / 分享卡片

QQ 里把 B 站视频转发成卡片，消息里**没有 http 文本**，链接藏在 `json` 消息段的 meta 里。
插件现在会从消息链里挖，不用你手动复制链接。

认两种结构：

```
com.tencent.miniapp_01  →  meta.detail_1.qqdocurl
com.tencent.structmsg   →  meta.news.jumpUrl
```

字段名不固定，所以是递归找 `qqdocurl` / `jumpUrl` / `jump_url` / `url` 这几个键，
最多钻 6 层、取前 3 条。`Share` 组件的 `url` 是直接字段，单独处理。

OneBot 的 json 段常把整段再包一层（`{"data": "<JSON 字符串>"}`），这个也解。

**注意**：卡片里的短链有过期时间。截图里那条 `b23.tv/DPBqgs` 我实测返回：

```json
{"code":-404,"message":"啥都没有","ttl":1}
```

短链失效了就没救，换成长链或者重新分享。这个是 B 站那边的问题，不是解析的问题。


## 冷却：多久能发

同会话两次解析之间有冷却，默认 5 秒。冷却期间再发链接会提示还要等多久：

```
刚发过，还要等 16 秒。
```

`/解析` 也会显示当前状态：

```
这个会话的自动解析：开
冷却 30 秒，还要等 16 秒
```

- `cooldown` 改秒数，0 表示不冷却
- `cooldown_hint` 关掉提示，冷却期间静默
- 提示本身有 60 秒节流，同一会话不会刷屏


## 下载提示

视频要下几十秒，下载前先回一句，免得群里以为机器人死了：

```
解析成功，已选 480P，正在下载，约 10 MB，稍后发你～
[视频]
```

- `download_notice_on` 关掉这句预告
- `download_notice` 自定义文案，支持 `{title}` `{quality}` `{size}` 三个占位符
- 占位符写错不会炸，回落到默认文案

**顺序**：先解析拿元信息（0.2 秒），发提示，再下载，最后发文字+视频。
所以提示是**真的**先到，不是下载完才一起发。


## 卡片解析的三种形态

QQ 转发卡片到 OneBot 这边有三种走法，插件都认：

| 形态 | 消息段 | 怎么取 |
| --- | --- | --- |
| 小程序卡片 | `json` | `meta.detail_1.qqdocurl` / `meta.news.jumpUrl` |
| 链接分享 | `share` | 组件的 `url` 字段，直接给 |
| 结构消息卡片 | `xml` | 正则抠 `url=` / `<qqdocurl>` 标签 |

**第三种是最坑的。** AstrBot 的 `ComponentTypes` 里根本没有 `xml` 这个类型——
上游 `components.py` 只到 `json` 和 `unknown`。协议端下发 `xml` 段时：

```
logger.warning(f"不支持的消息段类型，已忽略: {t}, data={m['data']}")
```

整段被丢，`message_obj.message` 里根本看不到它。所以插件会额外读
`message_obj.raw_message` 的原始 `message` 数组，直接扫 `xml` 段内容。

还兼容 CQ 码字符串格式（`post-format: string`）：

```
[CQ:xml,data=&lt;msg url=&quot;https://...&quot;/&gt;]
```

### 还是没反应怎么办

配置里把 `debug_segments` 打开。解析不到链接时日志会打这么一行：

```
[link_preview] 没找到链接 | message_str='...' | 消息链=['plain'] | raw 段=['xml']
```

`消息链` 里没有、`raw 段` 里有 → 说明走的是被上游丢弃的那条路；
两边都没有 → 卡片根本没到机器人这边，是协议端没转发。


### 还是不行：最后一道兜底

v1.1.5 加了暴力扫描：把整个事件对象递归摊平，不管卡片藏在哪个字段、
被包了几层、是不是 JSON 转义（`https:\/\/`），只要能摊成字符串就挖出来。

```
消息链 → json 段 → share 段 → raw_message 的 message 数组
      → CQ 码字符串 → 整个事件递归摊平（深度 8，防循环引用）
```

会过滤噪音域名（头像、CDN、QQ 内部链接）：

```
qpic.cn  qlogo.cn  qq.com  gtimg.cn  weixin.qq.com
douyinpic.com  hdslb.com  bilivideo.com  …
```

兜底命中时日志会写一行 `[link_preview] 暴力扫描兜底命中: <url>`。

如果连这个都没命中，把 `debug_segments` 打开后日志里的 `DUMP raw_message=` 那行发我，
那是事件对象的完整结构，照着它就能加出针对性适配。


## 还不行：/链接诊断

不用翻日志了。**引用那条卡片消息**，发：

```
/链接诊断
```

机器人会回一段结构：

```
消息链: ["Json keys=['app', 'prompt', 'meta']"]
raw 段: 拿不到
文本里的链接: 无
卡片提取: ['https://www.bilibili.com/video/BV1GJ411x7h7']
暴力扫描: ['https://www.bilibili.com/video/BV1GJ411x7h7']
```

四行分别对应：

| 行 | 说明 |
| --- | --- |
| 消息链 | AstrBot 解析出来的组件，`keys=` 是组件的 data 字段 |
| raw 段 | 原始事件的 message 数组，能看出有没有 `xml` |
| 文本里的链接 | 纯文本里扫到的 |
| 卡片提取 / 暴力扫描 | 插件实际挖到的 |

**全都没有** → 卡片真没到机器人这边，是协议端的事。
**卡片提取有、但没自动解析** → 那是黑白名单或冷却拦的，检查配置。

另外启动日志会打一行版本号，确认装的是不是新版：

```
[link_preview] v1.1.6 已加载 | 卡片解析=json/share/xml/暴力扫描
```

日志里看不到这行 → 插件压根没加载上。


### 卡片没解析时，自动打卡片内容

v1.1.7 起：**收到 `json` / `share` 卡片但一条链接都没挖到时，直接打 WARNING**，
不用你发任何指令：

```
[link_preview] 收到 json 卡片但没挖到链接，内容={'app': 'com.tencent.miniapp_01', 'meta': {...}}
```

把这一行发我，里面就是卡片的真实字段，照着加适配就行。

### 诊断指令的别名

`/链接诊断` 和 `/链路诊断` 都认，另外还有 `/诊断链接`、`/卡片诊断`。

**注意**：要先**引用那条卡片消息**再发指令，否则查的是你这条纯文本，当然没卡片。


### 诊断看不到卡片？现在能看到

**卡片和诊断指令是两条不同的消息。** 你发卡片，再发 `/链接诊断`，诊断查的是后面那条纯文本，
当然「卡片提取: 无」。v1.1.9 起改成：

1. **见到卡片就按群记一份**，诊断时回读「本群最近一条卡片（N 秒前）」
2. **引用卡片再发诊断**时，从 Reply 组件的 `chain` 里直接取

输出长这样：

```
消息链: ['Plain']
raw 段: 拿不到
文本里的链接: 无
卡片提取: 无
暴力扫描: 无
--- 本群最近一条卡片（12 秒前）---
卡片1[json]: {'app': 'com.tencent.miniapp_01', 'prompt': '[QQ小程序]哔哩哔哩', 'meta': {...}}
卡片1 提取: ['https://www.bilibili.com/video/BV1GJ411x7h7']
```

后面两行才是关键 —— 它们显示卡片里到底有什么、我们的提取器能不能认。

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

### 日志里看不到 [link_preview]？

AstrBot 可以在插件配置里单独设置每个插件的日志等级，日志也可能被路由到单独的文件。
所以别只盯着主日志——直接问：

```
/解析 版本
```

```
链接解析 v1.1.8
卡片解析: json / share / xml / 暴力扫描
配置项 25 个
```

有回应 = 插件加载正常。再打开 `debug_segments`，发一次卡片，诊断会直接回在群里。