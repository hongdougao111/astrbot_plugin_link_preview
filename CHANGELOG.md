# 更新日志

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

- 卡片提取原来只认 `qqdocurl` / `jumpUrl` / `url` 三个键，现在只要值里有 http 就收
- 卡片里的封面图（`.jpg` / `.png` 结尾）不再当成内容链接，优先取跳转页
- `_is_content_url` 过滤图片和音视频直链


## v1.1.5

### 新增

- **暴力兜底扫描**：把整个事件对象递归摊平找链接，不管卡片藏在哪个字段、
  包了几层、是不是 JSON 转义（`https:\/\/`），只要能摊成字符串就挖出来
- 噪音域名过滤：头像、CDN、QQ 内部链接（qpic.cn / qlogo.cn / gtimg.cn / hdslb.com …）不会误当内容
- 循环引用保护，深度上限 8

### 修复

- 递归深度从 4 提到 8，原来深一点的嵌套就挖不到
- 链接里的 `\/` 转义和 `&amp;` 实体都能还原