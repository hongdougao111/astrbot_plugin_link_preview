# 更新日志

## v1.1.4

### 修复

- **结构消息卡片（`xml` 段）解析不出来**。AstrBot 的 `ComponentTypes` 没有 `xml`，
  上游直接 `logger.warning('不支持的消息段类型，已忽略')` 整段丢掉，
  `message_obj.message` 里看不到。现在额外读 `message_obj.raw_message` 的原始
  `message` 数组，直接扫 `xml` 段，同时兼容 CQ 码字符串格式。
- 支持 XML 的两种写法：属性式 `url="..."` 和标签式 `<qqdocurl>...</qqdocurl>`，
  带 XML 转义和 `\/` 转义都能还原

### 新增

- `debug_segments` 配置：解析不到链接时把消息链和 raw 段的类型打进日志，
  一眼看出卡片是以什么形式到的


## v1.1.3

### 新增

- **下载前先回一句**：「解析成功，已选 480P，正在下载，约 10 MB，稍后发你～」
  下载要几十秒，什么都不说就发文件，群里会以为机器人死了
- `download_notice_on` 开关，`download_notice` 自定义文案（支持 `{title}` `{quality}` `{size}`）

### 变更

- 视频流程拆成两步：`_probe_video` 只解析拿元信息，`_download_media` 下载，
  提示能真的先到，而不是下载完才一起发


## v1.1.2

### 新增

- **冷却提示**：冷却期间发链接会回「刚发过，还要等 16 秒。」，不用猜为什么没反应
- `/解析` 状态里加一行当前冷却情况
- `cooldown_hint` 配置，可关掉提示
- 提示本身 60 秒节流，同一会话不刷屏

### 修复

- `_build_chain` 的通用 meta 回落分支没把结果包成消息列表，
  导致普通网页的解析结果按字符逐个当消息段发出去。现在统一返回 `[comps]`


## v1.1.1

### 新增

- **解析小程序 / 分享卡片**。QQ 里把视频转发成卡片时，消息里没有 http 文本，
  链接藏在 `json` 消息段的 meta 里，靠文本匹配扫不到。现在从消息链里挖。
  - `com.tencent.miniapp_01` → `meta.detail_1.qqdocurl`
  - `com.tencent.structmsg` → `meta.news.jumpUrl`
  - 字段名不固定，递归找 6 层，取前 3 条
  - `Share` 组件的 `url` 是直接字段，单独处理
  - 兼容 OneBot json 段的双层包裹 `{"data": "<JSON字符串>"}`
- `parse_cards` 配置项，可关

### 修复

- 主流程原来用 `if "http" not in text: return` 提前返回，卡片消息永远进不来


## v1.1.0

### 新增

- **点歌**：`/点 歌名` 或 `/点 歌手`，搜到能播的直接发语音，一条信息一条语音
- `netease_music` / `search_limit` / `max_audio_mb` 三个配置项

### 移除

- **抖音解析整个删了**。无 Cookie 时分享页只下发页面壳，
  `videoInfoRes.item_list` 是空的；PC UA 直接返回「验证码中间页」；
  旧接口 `/web/api/v2/aweme/iteminfo/` 返回空 body，
  `/aweme/v1/web/aweme/detail/` 返回 `403 Blocked by ArgusSecurityPlugin`。
  做签名算法又跟不上它前端改版，留个必然失败的解析器没意义。
  连带删掉 `douyin_cookie` 配置项。

### 修复

- 音频和视频一样，record 段必须独占一条消息，现在文字和语音分两条发
- 自测补「抖音正则已移除」「song_summary 字段压缩」两组断言

## v1.0.1

### 修复

- **视频发不出去**。OneBot v11 协议端硬约束：

  ```
  retcode=1400
  wording='message element "video" must be the only segment in a message'
  ```

  带文字的视频消息整条被拒，插件这边看着发了其实没发。
  `_build_video` 现在返回消息列表，文字一条、视频一条，主流程逐条 yield。

### 新增

- `video_send_mode` 配置，可切成发群文件（某些协议端更稳）
- 自测补「video 独占一条消息」的断言

## v1.0.0

首个版本。

### 平台

- **B 站**：走 `x/web-interface/view` + `x/player/playurl` 官方接口，
  支持 b23.tv 短链，标题、UP 主、时长、播放量齐全
- **网易云**：走 `api/song/detail`，歌名、歌手、专辑、封面
- **其他网页**：og:title / og:description / og:image / title / description

### 能力

- B 站链接自动下载视频发群，流式下载边收边写边数字节，
  超 `max_video_mb` 立刻中止删文件
- 缓存键用 `bvid + 清晰度`，不用 URL：直链每次签名都不同，用 URL 会重复下载
- 封面图落盘缓存，规避平台防盗链
- 按会话开关，一个群关掉不影响别的群，状态落盘重启不丢
- 域名白名单 / 黑名单、单条消息解析数量、会话冷却

### 指令

- `/解析` 看状态，`/解析 开` / `/解析 关` 切换（管理员）