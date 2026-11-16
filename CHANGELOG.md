# 更新日志

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
