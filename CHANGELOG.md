# 更新日志

## v1.3.0

### 新增

- **GitHub**：仓库页出语言、star、fork、协议、描述；用户页出 followers、仓库数、bio
- **B 站专栏**：`bilibili.com/read/cv<id>`，出标题、作者、阅读量、封面
- **B 站番剧**：`bilibili.com/bangumi/play/ss<id>`，出标题、评分、话数、更新信息、简介
- 新平台单独放在 `multi_platform.py`，不动 `resolvers.py` 主结构

### 未支持

贴吧 / 微博 / 知乎 / 小红书 —— 都实测过，全部被风控挡住
（403 安全验证页 / 需要登录态）。做进去也只会报失败，没加。


## v1.2.0

### 修复

参照 [Qfxaile/astrbot_plugin_multi_parser](https://github.com/Qfxaile/astrbot_plugin_multi_parser) 的
`ShareCardExtractor` 补了两处漏掉的路径：

- **`raw_message.message` 的段是 AstrBot 组件对象时解析不了**。原来只当 dict 处理，
  `Json` 组件的 `data` 根本没被读到
- **卡片字段只认 `qqdocurl` / `jumpUrl` / `url`**，漏了 `miniapp.pcJumpUrl`、
  `miniapp.legacyUrl`、`feed.jumpUrl` 这三种新版卡片的位置

### 变更

- 卡片 URL 字段清单对齐上游：`qqdocurl` / `jumpUrl` / `jump_url` / `url` /
  `pcJumpUrl` / `legacyUrl`
- raw 段的 `json` / `share` 段直接交给卡片解析器，不再只当 xml 内容扫


## v1.1.9

### 修复

- **`/链接诊断` 看不到卡片内容**。卡片和诊断指令是两条不同的消息，诊断时查的是后面那条
  纯文本。现在见到卡片就按群缓存一份，诊断时回读「本群最近一条卡片（N 秒前）」；
  引用卡片再发诊断时从 `Reply.chain` 里直接取


## v1.1.8

### 新增

- `debug_segments` 打开后，解析不到链接时诊断结果**直接回在群里**，不用翻日志
  （插件 logger 可能被路由到单独的文件）
- `/解析 版本` 查当前版本和配置项数量


## v1.1.7

### 新增

- **卡片挖不到链接时自动打 WARNING**，把卡片内容打出来，不用等用户发诊断指令

### 修复

- `/链接诊断` 加别名：`链路诊断` / `诊断链接` / `卡片诊断`（原来只认「链接」，发「链路」不生效）


## v1.1.6

### 新增

- **`/链接诊断` 指令**：引用卡片消息发这个，机器人把消息链、raw 段、各路子挖到的 URL
  全回给你，不用翻日志
- 启动日志打版本号：`[link_preview] v1.1.6 已加载 | 卡片解析=...`，
  看不到这行说明插件没加载

### 修复