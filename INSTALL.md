# 怎么用

## 一、装

压缩包已经打好了：`astrbot_plugin_link_preview.zip`（12.7 KB）

### 方式 A：WebUI 上传（最省事）

1. 打开 AstrBot WebUI，左边点 **插件**
2. 右上角 **安装插件** → 选 **上传文件** → 挑 `astrbot_plugin_link_preview.zip`
3. 装完在插件卡片上点 **重载插件**（刷新图标）
4. 卡片变绿、没有红色报错就成功了

### 方式 B：手动放目录

把整个 `astrbot_plugin_link_preview/` 文件夹复制到：

```
AstrBot/data/plugins/astrbot_plugin_link_preview/
```

然后 WebUI **插件** 页点重载，或者直接重启 AstrBot。

目录结构必须是这样，`main.py` 在插件文件夹的第一层：

```
data/plugins/
└── astrbot_plugin_link_preview/
    ├── main.py
    ├── metadata.yaml
    ├── _conf_schema.json
    └── requirements.txt
```

### 依赖

只有一个 `aiohttp`。AstrBot 自己就带着它（本机实测 3.14.5），
一般不用管。万一插件加载时报 `ModuleNotFoundError: aiohttp`：

```bash
pip install aiohttp
# 用 AstrBot 的虚拟环境的话
# AstrBot/venv/bin/pip install aiohttp      # Linux
# AstrBot\venv\Scripts\pip install aiohttp  # Windows
```

## 二、用

**发链接就行，不用打指令。**

- B 站链接 → 下载视频，回标题 + UP 主 + 文件大小 + 视频本体
- 网易云 → 回歌名、歌手、专辑、封面
- 其他网页 → 回标题、站点、简介、封面

**指令只有两个**（管理员才能用）：

```
/解析          看这个会话开没开
/解析 开       打开
/解析 关       关掉
```

按会话记，群 A 关了不影响群 B，重启不丢。

## 三、调

WebUI **插件** → 卡片右上角 **配置**，改完保存即时生效，不用重载。

最常调的三个：

| 想干什么 | 改哪个 |
| --- | --- |
| 只在几个站解析 | `whitelist` 填域名，如 `bilibili.com` |
| 别刷屏 | `max_links` 设 1，`cooldown` 设 10 |
| 解析完别让 AI 接话 | `stop_llm` 打开 |

**证书报错**：日志里出现 `CERTIFICATE_VERIFY_FAILED`，把 `insecure_ssl` 打开。

> `insecure_ssl` 会**完全跳过 HTTPS 证书校验**，等于关掉了中间人攻击的最基本防护。
> 只在日志明确报 `CERTIFICATE_VERIFY_FAILED`（机器缺 CA 证书库）时才打开，
> 修好证书库之后请关回去。默认是关的。
本机就踩到了这个（Windows 缺根证书库），实测打开后 example.com / python.org 都正常。

## 四、出问题怎么查

**插件卡片红色 / 加载失败**

点卡片上的 **重载**，WebUI 会弹具体错误。最常见两种：

- `ModuleNotFoundError: No module named 'aiohttp'` → 装依赖，见上一节
- `NameError` / `ImportError` → 文件没放对，`main.py` 必须在插件目录第一层

**装上了但发链接没反应**

按顺序查：

1. 配置页 `enabled` 是不是关着
2. `whitelist` 填了别的域名，当前站点不在里面
3. `blacklist` 把它拦了（默认拦 `t.cn`、`url.cn`）
4. `cooldown` 在冷却期内（同会话 5 秒）
5. 群里机器人没被 @ 或没开唤醒 —— 这是 AstrBot 的唤醒逻辑，不是插件的事

先试 `/解析 <url>`。指令能用、自动不能用，就是上面 1-4 之一；指令也不能用，是插件没加载。

**有文字没图**

- `send_image` 关着
- 页面本身没写 `og:image`
- 图超过 `max_image_mb`（默认 5 MB）
- 平台不支持图片（QQ 官方接口、钉钉对图片来源有限制）

**想看日志**

WebUI **日志** 页，或者 AstrBot 控制台。插件只在 `debug` 级别打细节，
出问题时把日志级别调到 DEBUG 再看。


## 五、平台解析

这些链接发出来就走专用接口，不用配置、不用登录：

| 平台 | 识别 | 拿到什么 |
| --- | --- | --- |
| 哔哩哔哩视频 | `bilibili.com/video/BV...`、`b23.tv` | 标题、UP 主、时长、播放量、封面，可下载视频 |
| 哔哩哔哩专栏 | `bilibili.com/read/cv...` | 标题、作者、阅读量、封面 |
| 哔哩哔哩番剧 | `bilibili.com/bangumi/play/ss...` | 标题、评分、话数、简介、封面 |
| 网易云音乐 | `music.163.com`、`163cn.tv` | 歌名、歌手、专辑、封面 |
| GitHub | `github.com/owner/repo`、`github.com/用户` | 语言、star、fork、协议、bio |
| 其他网页 | 任意 http(s) | 标题、来源、简介、封面 |

**点歌**：`/点 歌名` 或 `/点 歌手`，搜到能直接播的发语音。

**没支持的平台**：贴吧、微博、知乎、小红书、抖音。
这几个都实测过，接口要 Cookie 或登录态，硬做只会得到「解析失败」。

不想让某种链接走专用解析，把 `platform_resolvers` 关掉，全部回落通用 meta。


## 七、卸载

WebUI 插件卡片 → **卸载**，或者直接删 `data/plugins/astrbot_plugin_link_preview/`。

缓存图会留在 `data/plugin_data/astrbot_plugin_link_preview/img_cache/`，
不需要可以一起删，七天也会自己过期。