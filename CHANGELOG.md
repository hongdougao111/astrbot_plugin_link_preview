# 更新日志

## v1.3.1

### 修复

- **QQ 的 CDN 链接被误当内容页解析**。`multimedia.nt.qq.com.cn` 以 `qq.com.cn` 结尾，
  而黑名单里只有 `qq.com`，`endswith(".qq.com")` 对它为假，漏了
- 带 `fileid=` / `appid=` / `rkey=` 的 `/download` 接口一律不算内容页

### 新增

- 暴力扫描加了 B 站白名单优先：卡片里同时有预览图 CDN 和 B 站链接时，只取 B 站
  （思路来自 [chufeng/astrbot_plugin_bili_resolver](https://github.com/chufeng/astrbot_plugin_bili_resolver) 的 `_is_allowed_domain`）


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
