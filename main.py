# -*- coding: utf-8 -*-
"""链接解析插件：把聊天里的链接变成标题 + 简介 + 封面图。

设计要点：
- 用 aiohttp 异步抓取，绝不阻塞事件循环；
- 只读 </head> 之前的内容，超大页面不会拖垮内存；
- 封面图落盘缓存，避免平台侧被防盗链拦掉；
- 所有异常都在内部消化，插件不因一个坏链接崩掉。
"""

from __future__ import annotations

import asyncio
import hashlib
import html as html_lib
import os
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
import astrbot.api.message_components as Comp

try:  # 正常是作为包加载的
    from .resolvers import (
        MediaRef,
        Preview,
        bilibili_stream,
        is_blocked_page,
        match_bilibili,
        netease_audio_url,
        netease_search,
        pick as pick_resolver,
        song_summary,
    )
except ImportError:  # 万一被当独立文件加载
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from resolvers import (
        MediaRef,
        Preview,
        bilibili_stream,
        is_blocked_page,
        match_bilibili,
        netease_audio_url,
        netease_search,
        pick as pick_resolver,
        song_summary,
    )

# 链接提取：遇到空白、尖括号、中文标点、括号即截断，避免把句末符号吃进 URL
URL_RE = re.compile(r"https?://[^\s<>\"'）)】\]，。；：！？]+", re.IGNORECASE)
# URL 末尾可能粘上的标点
TRAILING = ".,;:!?)]}>'\"·…、。"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

CACHE_TTL = 7 * 24 * 3600  # 图片缓存保留 7 天


class _MetaParser(HTMLParser):
    """只关心 <meta> 和 <title>，遇到 </head> 就收手。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title: str = ""
        self._in_title = False
        self._done = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if self._done:
            return
        ad = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = ad.get("property") or ad.get("name") or ad.get("itemprop")
            content = ad.get("content", "")
            if key and content:
                key = key.strip().lower()
                # 先到的优先，og 一般排在前面
                self.meta.setdefault(key, content.strip())
        elif tag == "title":
            self._in_title = True
        elif tag == "body":
            self._done = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "head":
            self._done = True

    def handle_data(self, data: str) -> None:
        if self._in_title and not self.title:
            text = data.strip()
            if text:
                self.title = text


def _pick(meta: dict[str, str], *keys: str) -> str:
    for k in keys:
        v = meta.get(k)
        if v:
            return v
    return ""


def _domain_ok(host: str, patterns: list[str]) -> bool:
    """host 是否命中某条域名规则（支持子域）。"""
    host = host.lower().lstrip(".")
    for raw in patterns:
        p = str(raw).strip().lower()
        if not p:
            continue
        p = p.removeprefix("http://").removeprefix("https://").split("/")[0].lstrip(".")
        if not p:
            continue
        if host == p or host.endswith("." + p):
            return True
    return False


class LinkPreview(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._session: aiohttp.ClientSession | None = None
        self._last_at: dict[str, float] = {}
        self._hint_at: dict[str, float] = {}
        self._cache_dir: Path | None = None
        self._schema_defaults = self._load_schema_defaults()
        self._state: dict | None = None  # 会话开关，懒加载

    # ---------- 配置 ----------

    def _load_schema_defaults(self) -> dict:
        """拿不到运行时配置时的兜底，保证插件不会因为读不到配置而空转。"""
        import json

        path = Path(__file__).parent / "_conf_schema.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return {k: v.get("default") for k, v in raw.items() if isinstance(v, dict)}
        except Exception as e:  # 文件缺失或格式坏了都不致命
            logger.warning(f"[link_preview] 读取 _conf_schema.json 失败: {e}")
            return {}

    def _conf(self) -> dict:
        cfg = None
        try:
            cfg = self.get_config()  # v4.9+ Star 提供
        except Exception:
            cfg = None
        if cfg is None:
            try:
                cfg = self.context.get_config()
            except Exception:
                cfg = None
        merged = dict(self._schema_defaults)
        if cfg:
            try:
                for k in list(merged.keys()):
                    v = cfg.get(k, None)
                    if v is not None:
                        merged[k] = v
            except Exception:
                pass
        return merged

    # ---------- 会话开关 ----------

    def _state_path(self) -> Path:
        return self._data_dir() / "state.json"

    def _load_state(self) -> dict:
        """会话开关存在磁盘上，重启不丢。格式：{"off": ["会话id", ...]}"""
        if self._state is not None:
            return self._state
        import json

        path = self._state_path()
        data = {"off": [], "on": []}
        try:
            if path.exists():
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for key in ("off", "on"):
                        if isinstance(raw.get(key), list):
                            data[key] = [str(x) for x in raw[key]]
        except Exception as e:
            logger.warning(f"[link_preview] 读取开关状态失败，按全开处理: {e}")
        self._state = data
        return data

    def _save_state(self) -> None:
        import json

        if self._state is None:
            return
        path = self._state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.part")
            tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception as e:
            logger.warning(f"[link_preview] 保存开关状态失败: {e}")

    def _is_on(self, session_id: str) -> bool:
        """会话自己关过就是关。

        全局 enabled 只当"从没动过开关时的默认值"，不作为硬拦。
        否则 WebUI 里关掉全局之后，/解析 开会显示成功却还是不干活。
        """
        if session_id in self._load_state()["off"]:
            return False
        return bool(self._conf().get("enabled", True)) or session_id in self._load_state()["on"]

    def _set_on(self, session_id: str, on: bool) -> None:
        state = self._load_state()
        off, onl = state["off"], state["on"]
        if on:
            while session_id in off:
                off.remove(session_id)
            if session_id not in onl:
                onl.append(session_id)  # 显式开过，压过全局 enabled
        else:
            while session_id in onl:
                onl.remove(session_id)
            if session_id not in off:
                off.append(session_id)
        self._save_state()

    # ---------- 资源 ----------

    async def _get_session(self, timeout_s: int, insecure: bool = False) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # insecure 只在用户明确要求时生效：有些机器缺 CA 库，校验一开就全挂
            conn = aiohttp.TCPConnector(ssl=False) if insecure else None
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout_s, connect=min(timeout_s, 8)),
                headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
                connector=conn,
            )
            self._session_insecure = insecure
        elif getattr(self, "_session_insecure", False) != insecure:
            # 开关变了就重建，避免一个会话里两种策略混着用
            await self._session.close()
            self._session = None
            return await self._get_session(timeout_s, insecure)
        return self._session

    @staticmethod
    def _decode(raw: bytes, charset: str | None) -> str:
        """先按响应头 charset，没有就在头部几十字节里找 meta charset，最后退 utf-8。"""
        cand = (charset or "").strip().lower()
        if not cand:
            head = raw[:2048].decode("ascii", errors="ignore").lower()
            m = re.search(r'charset\s*=\s*["\']?([a-z0-9_-]+)', head)
            cand = m.group(1) if m else "utf-8"
        if cand in ("gb2312", "gbk", "gb18030"):
            cand = "gb18030"  # 向上兼容，gbk 页面用这个解不会错
        try:
            return raw.decode(cand, errors="replace")
        except LookupError:
            return raw.decode("utf-8", errors="replace")

    def _data_dir(self) -> Path:
        """持久化目录，按官方约定放在 data/plugin_data/<插件名>/ 下。"""
        if self._cache_dir is not None:
            return self._cache_dir
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            base = Path(get_astrbot_data_path()) / "plugin_data" / self.name
        except Exception:
            base = Path(__file__).parent / "data"
        base.mkdir(parents=True, exist_ok=True)
        self._cache_dir = base
        return base

    def _prune_cache(self) -> None:
        img_dir = self._data_dir() / "img_cache"
        if not img_dir.exists():
            return
        now = time.time()
        for f in img_dir.iterdir():
            try:
                if f.is_file() and now - f.stat().st_mtime > CACHE_TTL:
                    f.unlink()
            except OSError:
                pass

    # ---------- 抓取与解析 ----------

    async def _fetch_html(self, url: str, conf: dict) -> tuple[str, str] | None:
        """返回 (最终 URL, HTML 文本)；失败返回 None。"""
        timeout_s = int(conf.get("timeout") or 10)
        max_bytes = int(conf.get("max_html_kb") or 512) * 1024
        headers = {"User-Agent": conf.get("user_agent") or DEFAULT_UA}
        extra = conf.get("extra_headers")
        if isinstance(extra, dict):
            headers.update({str(k): str(v) for k, v in extra.items()})

        insecure = bool(conf.get("insecure_ssl"))
        session = await self._get_session(timeout_s, insecure)
        try:
            async with session.get(url, headers=headers, allow_redirects=True) as resp:
                if resp.status >= 400:
                    logger.debug(f"[link_preview] {url} 返回 {resp.status}")
                    return None
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if ctype and not any(t in ctype for t in ("text/html", "application/xhtml", "text/plain")):
                    logger.debug(f"[link_preview] {url} 不是 HTML: {ctype}")
                    return None
                raw = bytearray()
                # 边读边判断，读到 </head> 已经够了
                async for chunk in resp.content.iter_chunked(16384):
                    raw.extend(chunk)
                    if len(raw) >= max_bytes:
                        break
                    if b"</head>" in chunk.lower():
                        break
                return str(resp.url), self._decode(bytes(raw), resp.charset)
        except asyncio.TimeoutError:
            logger.debug(f"[link_preview] {url} 超时")
            return None
        except aiohttp.ClientError as e:
            logger.debug(f"[link_preview] {url} 请求失败: {e}")
            return None
        except Exception as e:
            logger.warning(f"[link_preview] 抓取 {url} 出现未预期错误: {e}")
            return None

    async def _parse(self, url: str, conf: dict) -> dict | None:
        got = await self._fetch_html(url, conf)
        if not got:
            return None
        final_url, text = got

        parser = _MetaParser()
        try:
            parser.feed(text[: int(conf.get("max_html_kb") or 512) * 1024])
            parser.close()
        except Exception as e:
            logger.debug(f"[link_preview] HTML 解析失败 {url}: {e}")
            return None

        meta = parser.meta
        title = _pick(meta, "og:title", "twitter:title", "title") or parser.title
        desc = _pick(meta, "og:description", "twitter:description", "description")
        image = _pick(meta, "og:image", "og:image:url", "twitter:image", "twitter:image:src")
        site = _pick(meta, "og:site_name", "application-name")

        title = html_lib.unescape(title or "").strip()
        desc = html_lib.unescape(desc or "").strip()
        if not title:
            return None  # 连标题都没有的页面，回出来也没意思

        if is_blocked_page(title):
            logger.debug(f"[link_preview] {url} 落到风控中间页，放弃")
            return None

        limit = int(conf.get("desc_length") or 0)
        if limit > 0 and len(desc) > limit:
            desc = desc[:limit].rstrip() + "…"

        host = urlparse(final_url).hostname or ""
        if not site:
            site = host.removeprefix("www.")

        image_url = urljoin(final_url, image) if image else ""
        return {
            "url": final_url,
            "title": title,
            "desc": desc,
            "site": site,
            "host": host,
            "image": image_url,
        }

    async def _cache_image(self, url: str, conf: dict, referer: str = "") -> str | None:
        """把封面图下载到本地，返回文件路径。失败返回 None。

        referer 必须给对：B 站、抖音的图床都查这个，给错了直接 403。
        """
        max_bytes = int(float(conf.get("max_image_mb") or 5) * 1024 * 1024)
        img_dir = self._data_dir() / "img_cache"
        img_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        for ext in (".jpg", ".png", ".gif", ".webp"):
            hit = img_dir / (key + ext)
            if hit.exists() and hit.stat().st_size > 0:
                return str(hit)

        timeout_s = int(conf.get("timeout") or 10)
        session = await self._get_session(timeout_s, bool(conf.get("insecure_ssl")))
        headers = {
            "User-Agent": conf.get("user_agent") or DEFAULT_UA,
            "Referer": referer or url,
        }
        try:
            async with session.get(url, headers=headers, allow_redirects=True) as resp:
                if resp.status >= 400:
                    return None
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "image" not in ctype:
                    return None
                length = resp.headers.get("Content-Length")
                if length and length.isdigit() and int(length) > max_bytes:
                    logger.debug(f"[link_preview] 封面图过大: {length} bytes")
                    return None
                buf = bytearray()
                async for chunk in resp.content.iter_chunked(32768):
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        logger.debug("[link_preview] 封面图超过上限，放弃")
                        return None
            if not buf:
                return None
            if ctype.startswith("image/png"):
                ext = ".png"
            elif ctype.startswith("image/gif"):
                ext = ".gif"
            elif ctype.startswith("image/webp"):
                ext = ".webp"
            else:
                ext = ".jpg"
            out = img_dir / (key + ext)
            tmp = out.with_suffix(out.suffix + ".part")
            tmp.write_bytes(bytes(buf))
            tmp.replace(out)
            return str(out)
        except Exception as e:
            logger.debug(f"[link_preview] 下载封面图失败 {url}: {e}")
            return None

    # ---------- 主流程 ----------

    async def _resolve(self, url: str, conf: dict) -> Preview | None:
        """专用解析器优先，拿不到再退回通用 meta 抓取。"""
        if not conf.get("platform_resolvers", True):
            return None
        fn = pick_resolver(url)
        if fn is None:
            return None
        timeout_s = int(conf.get("timeout") or 10)
        session = await self._get_session(timeout_s, bool(conf.get("insecure_ssl")))
        try:
            got = await fn(session, url)
        except Exception as e:
            logger.debug(f"[link_preview] 平台解析器处理 {url} 出错: {e}")
            return None
        if got:
            logger.debug(f"[link_preview] {url} 由专用解析器命中: {got.site}")
        return got

    QUALITY_LABELS = {16: "360P", 32: "480P", 64: "720P", 80: "1080P"}

    def _quality_label(self, qn: int) -> str:
        return self.QUALITY_LABELS.get(int(qn), f"{qn}")

    async def _probe_video(self, url: str, conf: dict):
        """只解析，不下载。返回 (MediaRef, Preview) 或 None。"""
        timeout_s = int(conf.get("timeout") or 10)
        session = await self._get_session(timeout_s, bool(conf.get("insecure_ssl")))
        try:
            got = await bilibili_stream(session, url, int(conf.get("video_quality") or 32))
        except Exception as e:
            logger.info(f"[link_preview] 取视频直链失败 {url}: {e}")
            return None
        return got

    def _download_notice(self, preview, ref, conf: dict) -> str:
        """下载前的那句预告。"""
        qn = int(conf.get("video_quality") or 32)
        label = self._quality_label(qn)
        size = f"，约 {ref.size // 1024 // 1024} MB" if ref.size else ""
        template = str(conf.get("download_notice") or "").strip()
        if template:
            try:
                return template.format(title=preview.title, quality=label, size=size.lstrip("，"))
            except Exception:
                pass
        return f"解析成功，已选 {label}，正在下载{size}，稍后发你～"

    async def _video_chain(self, preview, path: str, conf: dict):
        """下载完构造消息：文字一条、视频一条。"""
        lines = [f"【{preview.title}】"]
        if preview.extra:
            lines.append(preview.extra)
        lines.append(preview.url)
        lines.append(f"文件 {os.path.getsize(path) // 1024 // 1024} MB")

        media = self._media_component(path, conf)
        if media is None:
            return [[Comp.Plain("\n".join(lines))]]
        # OneBot 硬约束：video 段必须独占一条消息，所以文字和视频分开
        return [[Comp.Plain("\n".join(lines))], [media]]

    async def _build_video(self, url: str, conf: dict):
        """B 站视频：解析 + 下载，一次性返回全部消息。给 /下载 指令用。"""
        if not conf.get("download_video"):
            return None
        got = await self._probe_video(url, conf)
        if not got:
            return None
        ref, preview = got

        path = await self._download_media(ref, conf)
        if not path:
            return [await self._build_plain(preview, conf)]
        return await self._video_chain(preview, path, conf)

    async def _build_plain(self, info: Preview, conf: dict):
        """只有文字 + 封面，不下载媒体。"""
        lines = [f"【{info.title}】"]
        if info.site and info.site not in info.title:
            lines.append(f"来源：{info.site}")
        if info.extra:
            lines.append(info.extra)
        if info.desc:
            lines.append(info.desc)
        lines.append(info.url)
        comps = [Comp.Plain("\n".join(lines))]
        if conf.get("send_image") and info.image:
            path = await self._cache_image(info.image, conf, info.referer)
            if path:
                try:
                    comps.append(Comp.Image.fromFileSystem(path))
                except Exception as e:
                    logger.debug(f"[link_preview] 构造图片组件失败: {e}")
        return comps

    async def _build_chain(self, url: str, conf: dict):
        """非视频的解析。视频走 on_any_message 里的专门分支，因为要先发提示再下。"""
        info = await self._resolve(url, conf)
        if info:
            return [await self._build_plain(info, conf)]

        # 回落：通用 meta 解析
        info = await self._parse(url, conf)
        if not info:
            return None

        lines = [f"【{info['title']}】"]
        if info["site"] and info["site"] not in info["title"]:
            lines.append(f"来源：{info['site']}")
        if info["desc"]:
            lines.append(info["desc"])
        lines.append(info["url"])

        comps = [Comp.Plain("\n".join(lines))]
        if conf.get("send_image") and info["image"]:
            path = await self._cache_image(info["image"], conf)
            if path:
                try:
                    comps.append(Comp.Image.fromFileSystem(path))
                except Exception as e:
                    logger.debug(f"[link_preview] 构造图片组件失败: {e}")
        # 和 _build_video 一样，返回"消息列表"，每条一个组件列表
        return [comps]

    # ---------- 媒体下载 ----------

    async def _download_media(self, ref, conf: dict) -> str | None:
        """把媒体流式下载到本地，返回文件路径。超过上限就中止并删掉半个文件。"""
        max_bytes = int(float(conf.get("max_video_mb") or 50) * 1024 * 1024)
        media_dir = self._data_dir() / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        key = ref.cache_key or hashlib.sha1(ref.url.encode("utf-8")).hexdigest()[:16]
        # 文件名只留安全字符，bvid 里可能有大小写字母和数字，直接拼没问题
        key = re.sub(r"[^0-9A-Za-z_.-]", "_", key)
        out = media_dir / f"{key}{ref.ext}"
        if out.exists() and out.stat().st_size > 0:
            return str(out)  # 同一个视频不重复下载

        if ref.size and ref.size > max_bytes:
            logger.info(
                f"[link_preview] 媒体 {ref.size // 1024 // 1024}MB 超过上限 "
                f"{max_bytes // 1024 // 1024}MB，跳过"
            )
            return None

        timeout_s = max(int(conf.get("timeout") or 10), 30)
        session = await self._get_session(timeout_s, bool(conf.get("insecure_ssl")))
        headers = {"User-Agent": conf.get("user_agent") or DEFAULT_UA}
        if ref.referer:
            headers["Referer"] = ref.referer

        tmp = out.with_suffix(out.suffix + ".part")
        got = 0
        try:
            async with session.get(ref.url, headers=headers, allow_redirects=True) as resp:
                if resp.status >= 400:
                    logger.info(f"[link_preview] 媒体下载失败，HTTP {resp.status}")
                    return None
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if ctype and not any(t in ctype for t in ("video", "audio", "octet-stream")):
                    logger.info(f"[link_preview] 媒体响应不是音视频: {ctype}")
                    return None
                with tmp.open("wb") as fh:
                    async for chunk in resp.content.iter_chunked(65536):
                        fh.write(chunk)
                        got += len(chunk)
                        if got > max_bytes:
                            raise ValueError("超过大小上限")
            if got == 0:
                tmp.unlink(missing_ok=True)
                return None
            tmp.replace(out)
            logger.info(f"[link_preview] 媒体已下载 {out.name} {got // 1024} KB")
            return str(out)
        except ValueError:
            logger.info(f"[link_preview] 媒体超过 {max_bytes // 1024 // 1024}MB，中止")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        except asyncio.TimeoutError:
            logger.info("[link_preview] 媒体下载超时")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        except Exception as e:
            logger.info(f"[link_preview] 媒体下载出错: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return None

    def _media_component(self, path: str, conf: dict):
        """把本地文件包成一个消息组件。按 video_send_mode 选视频还是文件。

        注意：返回的是**单个**组件，调用方必须让它独占一条消息。
        """
        mode = str(conf.get("video_send_mode") or "video")
        if mode == "file":
            try:
                return Comp.File(file=path, name=os.path.basename(path))
            except Exception as e:
                logger.warning(f"[link_preview] File 组件不可用: {e}")
                return None
        try:
            return Comp.Video.fromFileSystem(path=path)
        except Exception as e:
            logger.debug(f"[link_preview] Video 组件不可用，退回 File: {e}")
        try:
            return Comp.File(file=path, name=os.path.basename(path))
        except Exception as e:
            logger.warning(f"[link_preview] 构造媒体组件失败: {e}")
            return None

    # ---------- 小程序 / 卡片 ----------

    # QQ 小程序卡片走 json 消息段，里面的链接藏在几层 meta 里。
    # 常见的两种结构：
    #   com.tencent.miniapp_01 -> meta.detail_1.qqdocurl
    #   com.tencent.structmsg  -> meta.news.jumpUrl
    _CARD_URL_KEYS = ("qqdocurl", "jumpUrl", "jump_url", "url")

    def _urls_from_card(self, data) -> list[str]:
        """从卡片 JSON 里挖出 URL。结构不固定，所以递归找。"""
        # OneBot 的 json 段常把整段再包一层：{"data": "<JSON 字符串>"}
        import json as _json

        for _ in range(3):
            if isinstance(data, str):
                try:
                    data = _json.loads(data)
                except Exception:
                    return []
            elif isinstance(data, dict) and isinstance(data.get("data"), str):
                data = data["data"]
            else:
                break

        found: list[str] = []

        def walk(node, depth=0):
            if depth > 6 or len(found) >= 3:
                return
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in self._CARD_URL_KEYS and isinstance(value, str):
                        v = value.strip()
                        if v.startswith("http") and v not in found:
                            found.append(v)
                    else:
                        walk(value, depth + 1)
            elif isinstance(node, list):
                for item in node:
                    walk(item, depth + 1)
            elif isinstance(node, str) and node.startswith("http") and len(node) < 300:
                if node not in found and "qq.com" not in node:
                    found.append(node)

        try:
            walk(data)
        except Exception as e:
            logger.debug(f"[link_preview] 解析卡片失败: {e}")
        return found

    # XML 卡片（Lagrange / go-cqhttp 老版下发形如
    # <msg serviceID="1" url="https://..." brief="...">...</msg>）
    _XML_ATTR_URL = re.compile(r"""(?:url|qqdocurl|jumpUrl)\s*=\s*["']([^"']+)["']""", re.I)
    _XML_TAG_URL = re.compile(r"<(?:qqdocurl|jumpUrl|url)>\s*(https?://[^<\s]+)\s*</", re.I)

    def _urls_from_xml(self, text: str) -> list[str]:
        """从 XML 卡片里抠 URL。属性式和标签式两种都认。"""
        if not text or len(text) > 200000:
            return []
        found: list[str] = []
        for rx in (self._XML_ATTR_URL, self._XML_TAG_URL):
            for m in rx.finditer(text):
                v = html_lib.unescape(m.group(1)).strip()
                # XML 里常见转义 &amp; 和 \/ 两种写法
                v = v.replace("\\/", "/")
                if v.startswith("http") and v not in found and "qq.com" not in v:
                    found.append(v)
                if len(found) >= 3:
                    return found
        return found

    def _scan_raw_message(self, event) -> list[str]:
        """从原始 OneBot 事件里扫卡片。

        AstrBot 的 ComponentTypes 里没有 "xml" 这个类型（上游 components.py 只到
        json/unknown），协议端下发 xml 段时会被整段丢弃，消息链里根本看不到。
        所以这里回到 event.message_obj.raw_message 读原样的 message 数组。
        """
        obj = getattr(event, "message_obj", None)
        raw = getattr(obj, "raw_message", None) if obj else None
        if raw is None:
            return []

        segments = None
        try:
            segments = getattr(raw, "message", None)
            if segments is None and isinstance(raw, dict):
                segments = raw.get("message")
            # 有的实现把整个事件对象塞进 raw.message，再取一层
            for _ in range(2):
                if isinstance(segments, dict):
                    segments = segments.get("message")
                else:
                    break
        except Exception:
            segments = None

        out: list[str] = []

        def take(text):
            for u in self._urls_from_xml(text):
                if u not in out:
                    out.append(u)

        if isinstance(segments, list):
            for seg in segments:
                try:
                    data = seg.get("data") if isinstance(seg, dict) else getattr(seg, "data", None)
                    if not isinstance(data, dict):
                        continue
                    for key in ("xml", "json", "content"):
                        val = data.get(key)
                        if isinstance(val, str) and val:
                            take(val)
                except Exception:
                    continue
        elif isinstance(segments, str):
            # CQ 码格式（post-format: string），把 [CQ:xml,data=...] 解出来
            for m in re.finditer(r"\[CQ:(?:xml|json),([^\]]+)\]", segments):
                payload = html_lib.unescape(m.group(1))
                take(payload)
        return out

    def _log_segments(self, event) -> None:
        """把消息链和原始事件的段类型打到日志，排查"为什么没解析"用。"""
        obj = getattr(event, "message_obj", None)
        chain = getattr(obj, "message", None) if obj else None
        kinds = []
        for comp in (chain or []):
            try:
                t = getattr(comp, "type", "")
                kinds.append(str(getattr(t, "value", t)))
            except Exception:
                kinds.append("?")

        raw_kinds = []
        raw = getattr(obj, "raw_message", None) if obj else None
        segs = getattr(raw, "message", None) if raw is not None else None
        if isinstance(segs, dict):
            segs = segs.get("message")
        if isinstance(segs, list):
            for seg in segs:
                try:
                    raw_kinds.append(seg.get("type") if isinstance(seg, dict) else type(seg).__name__)
                except Exception:
                    raw_kinds.append("?")
        elif isinstance(segs, str):
            raw_kinds.append(f"str({len(segs)})")

        logger.info(
            f"[link_preview] 没找到链接 | message_str={ (event.message_str or '')[:60]!r} "
            f"| 消息链={kinds} | raw 段={raw_kinds}"
        )

    def _take_card_urls(self, event, conf: dict) -> list[str]:
        """扫消息链里的小程序 / 分享卡片。message_str 只有纯文本，卡片不在里面。"""
        obj = getattr(event, "message_obj", None)
        chain = getattr(obj, "message", None) if obj else None

        out: list[str] = []
        for comp in (chain or []):
            try:
                raw_type = getattr(comp, "type", "")
                type_name = getattr(raw_type, "value", raw_type)
                kind = str(type_name).lower()
                if kind == "share":
                    # Share 组件的 url 是直接字段，不套在 data 里
                    u = str(getattr(comp, "url", "") or "").strip()
                    if u.startswith("http") and u not in out:
                        out.append(u)
                    continue
                if kind != "json":
                    continue

                data = getattr(comp, "data", None)
                # OneBot 的 json 段常见两层：data.data 还是个 JSON 字符串
                for _ in range(3):
                    if isinstance(data, str):
                        try:
                            import json as _json

                            data = _json.loads(data)
                        except Exception:
                            data = None
                            break
                    elif isinstance(data, dict) and isinstance(data.get("data"), str):
                        data = data["data"]
                    else:
                        break
                if not isinstance(data, dict):
                    continue
                for u in self._urls_from_card(data):
                    if u not in out:
                        out.append(u)
            except Exception as e:
                logger.debug(f"[link_preview] 处理消息段失败: {e}")

        # 复用同一套黑白名单
        allowed: list[str] = []
        for u in out:
            host = urlparse(u).hostname or ""
            if not host:
                continue
            if _domain_ok(host, conf.get("blacklist") or []):
                continue
            white = conf.get("whitelist") or []
            if white and not _domain_ok(host, white):
                continue
            allowed.append(u)

        # 消息链里没有（xml 段被上游丢了），回到原始事件再扫一遍
        if not allowed:
            for u in self._scan_raw_message(event):
                host = urlparse(u).hostname or ""
                if not host:
                    continue
                if _domain_ok(host, conf.get("blacklist") or []):
                    continue
                white = conf.get("whitelist") or []
                if white and not _domain_ok(host, white):
                    continue
                if u not in allowed:
                    allowed.append(u)

        return allowed[: int(conf.get("max_links") or 1)]

    def _take_urls(self, text: str, conf: dict) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for m in URL_RE.finditer(text or ""):
            u = m.group(0).rstrip(TRAILING)
            if not u or u in seen:
                continue
            host = urlparse(u).hostname or ""
            if not host:
                continue
            black = conf.get("blacklist") or []
            white = conf.get("whitelist") or []
            if _domain_ok(host, black):
                continue
            if white and not _domain_ok(host, white):
                continue
            seen.add(u)
            found.append(u)
            if len(found) >= int(conf.get("max_links") or 1):
                break
        return found

    def _cooldown_left(self, session_id: str, conf: dict) -> int:
        """还要等几秒。0 表示现在能发，并且已经记下这次的时间。"""
        cd = int(conf.get("cooldown") or 0)
        if cd <= 0:
            return 0
        now = time.time()
        last = self._last_at.get(session_id, 0)
        left = int(round(cd - (now - last)))
        if left > 0:
            return left
        self._last_at[session_id] = now
        # 顺手清掉过期的键，避免长期运行无限增长
        if len(self._last_at) > 2048:
            for k in [k for k, v in self._last_at.items() if now - v > 3600]:
                self._last_at.pop(k, None)
        return 0

    def _cooling(self, session_id: str, conf: dict) -> bool:
        """老接口，保留给自测用。"""
        return self._cooldown_left(session_id, conf) > 0

    @staticmethod
    def _fmt_wait(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds} 秒"
        m, s = divmod(seconds, 60)
        return f"{m} 分 {s} 秒" if s else f"{m} 分钟"

    def _hint_once(self, session_id: str, gap: int = 60) -> bool:
        """冷却提示的节流：同会话 60 秒内只提示一次，免得刷屏。"""
        now = time.time()
        if now - self._hint_at.get(session_id, 0) < gap:
            return False
        self._hint_at[session_id] = now
        return True

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_any_message(self, event: AstrMessageEvent):
        """自动解析：注意不要用 filter.regex，避免和其他插件的正则抢消息。"""
        conf = self._conf()
        if not self._is_on(event.unified_msg_origin):
            return

        # 机器人自己发的消息不处理，防止自激
        try:
            if event.get_sender_id() == event.get_self_id():
                return
        except Exception:
            pass

        text = event.message_str or ""
        urls = self._take_urls(text, conf) if "http" in text else []
        # 小程序 / 分享卡片不带 http 文本，得从消息链里挖
        if not urls and conf.get("parse_cards", True):
            urls = self._take_card_urls(event, conf)
        if not urls:
            # 排查用：把这条消息的段类型摊开，一眼看出卡片是以什么形式到的
            if conf.get("debug_segments"):
                self._log_segments(event)
            return

        sid = event.unified_msg_origin
        left = self._cooldown_left(sid, conf)
        if left > 0:
            logger.debug(f"[link_preview] 会话冷却中，还要 {left} 秒")
            if conf.get("cooldown_hint", True) and self._hint_once(sid):
                yield event.plain_result(f"刚发过，还要等 {self._fmt_wait(left)}。")
            return

        for url in urls:
            # B 站视频单独走：先解析拿元信息，回一句"正在下载"，下完再发文件。
            # 下载要几十秒，什么都不说就发文件，群里会以为机器人死了。
            if conf.get("download_video") and match_bilibili(url):
                handled = False
                try:
                    got = await self._probe_video(url, conf)
                except Exception as e:
                    logger.warning(f"[link_preview] 解析视频失败 {url}: {e}")
                    got = None
                if got:
                    ref, preview = got
                    if conf.get("download_notice_on", True):
                        yield event.plain_result(self._download_notice(preview, ref, conf))
                    try:
                        path = await self._download_media(ref, conf)
                    except Exception as e:
                        logger.warning(f"[link_preview] 下载视频失败 {url}: {e}")
                        path = None
                    if path:
                        for comps in await self._video_chain(preview, path, conf):
                            yield event.chain_result(comps)
                        if conf.get("stop_llm"):
                            event.stop_event()
                        continue
                    # 下载失败退回预览
                    yield event.chain_result(await self._build_plain(preview, conf))
                    handled = True
                if handled:
                    continue
                # 视频没解析出来，走通用流程兜底

            try:
                chain = await self._build_chain(url, conf)
            except Exception as e:
                logger.warning(f"[link_preview] 处理 {url} 异常: {e}")
                chain = None
            if chain:
                for comps in chain:
                    yield event.chain_result(comps)
                if conf.get("stop_llm"):
                    event.stop_event()  # 由插件接管，不再走 AI 回复
            elif not conf.get("silent_on_fail", True):
                yield event.plain_result(f"这个链接没能解析出来：{url}")

    # ---------- 点歌 ----------

    async def _pick_playable(self, session, songs: list) -> list:
        """从搜索结果里挑出真能播的，最多三条。并行探测，别一个个等。"""

        async def probe(song):
            sm = song_summary(song)
            got = await netease_audio_url(session, sm["id"])
            return (sm, got) if got else None

        results = await asyncio.gather(
            *(probe(s) for s in songs), return_exceptions=True
        )
        out = []
        for r in results:
            if isinstance(r, Exception) or r is None:
                continue
            out.append(r)
        return out

    async def _fetch_audio(self, url: str, conf: dict, song_id: int) -> str | None:
        """下载音频到本地。返回文件路径。"""
        max_bytes = int(float(conf.get("max_audio_mb") or 12) * 1024 * 1024)
        music_dir = self._data_dir() / "music"
        music_dir.mkdir(parents=True, exist_ok=True)
        out = music_dir / f"ne_{song_id}.mp3"
        if out.exists() and out.stat().st_size > 0:
            return str(out)

        timeout_s = max(int(conf.get("timeout") or 10), 30)
        session = await self._get_session(timeout_s, bool(conf.get("insecure_ssl")))
        headers = {
            "User-Agent": conf.get("user_agent") or DEFAULT_UA,
            "Referer": "https://music.163.com/",
        }
        tmp = out.with_suffix(".mp3.part")
        got = 0
        try:
            async with session.get(url, headers=headers, allow_redirects=True) as resp:
                if "audio" not in (resp.headers.get("Content-Type") or "").lower():
                    return None
                with tmp.open("wb") as fh:
                    async for chunk in resp.content.iter_chunked(65536):
                        fh.write(chunk)
                        got += len(chunk)
                        if got > max_bytes:
                            raise ValueError("超过大小上限")
            if got == 0:
                tmp.unlink(missing_ok=True)
                return None
            tmp.replace(out)
            return str(out)
        except ValueError:
            logger.info(f"[link_preview] 音频超过 {max_bytes // 1024 // 1024}MB，放弃")
            tmp.unlink(missing_ok=True)
            return None
        except Exception as e:
            logger.info(f"[link_preview] 下载音频失败: {e}")
            tmp.unlink(missing_ok=True)
            return None

    @filter.command("点")
    async def song_cmd(self, event: AstrMessageEvent, keyword: str = ""):
        """点歌：/点 起风了 或 /点 周杰伦"""
        conf = self._conf()
        kw = (keyword or "").strip()
        if not kw:
            yield event.plain_result("用法：/点 歌名 或 /点 歌手")
            return
        if not conf.get("netease_music", True):
            yield event.plain_result("点歌关着，去插件配置里打开。")
            return

        timeout_s = int(conf.get("timeout") or 10)
        session = await self._get_session(timeout_s, bool(conf.get("insecure_ssl")))

        songs = await netease_search(session, kw, int(conf.get("search_limit") or 8))
        if not songs:
            yield event.plain_result(f"没搜到「{kw}」。")
            return

        picked = await self._pick_playable(session, songs[: int(conf.get("search_limit") or 8)])
        if not picked:
            yield event.plain_result(
                f"「{kw}」搜到了，但没有能直接播的（可能是 VIP 或者版权受限）。"
            )
            return

        sm, (audio_url, _size) = picked[0]
        path = await self._fetch_audio(audio_url, conf, sm["id"])
        if not path:
            yield event.plain_result("下下来了但存不住，换个试试。")
            return

        minutes, seconds = divmod(sm["duration"], 60)
        yield event.chain_result([Comp.Plain(
            f"♪ {sm['name']} - {sm['artists']}\n{sm['album']} · {minutes}:{seconds:02d}"
        )])
        try:
            # 和视频一样：record 段也得独占一条消息
            yield event.chain_result([Comp.Record(file=path, url=path)])
        except Exception as e:
            logger.warning(f"[link_preview] 语音组件失败，改发文件: {e}")
            try:
                yield event.chain_result([Comp.File(file=path, name=f"{sm['name']}.mp3")])
            except Exception as e2:
                yield event.plain_result(f"音频发不出去：{e2}")

    # ---------- 指令 ----------

    @filter.command("解析")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def toggle_cmd(self, event: AstrMessageEvent, action: str = ""):
        """开关自动解析：/解析 开 | /解析 关 | /解析"""
        sid = event.unified_msg_origin
        act = (action or "").strip().lower()

        if act in ("开", "on", "1", "开启", "打开"):
            self._set_on(sid, True)
            yield event.plain_result("好，这个会话的自动解析开了。发链接就行。")
            return
        if act in ("关", "off", "0", "关闭", "关掉"):
            self._set_on(sid, False)
            yield event.plain_result("关了这个会话的自动解析。要开回来发 /解析 开。")
            return

        here = "开" if self._is_on(sid) else "关"
        conf = self._conf()
        cd = int(conf.get("cooldown") or 0)
        if cd <= 0:
            wait = "没设冷却，随时能发"
        else:
            left = int(round(cd - (time.time() - self._last_at.get(sid, 0))))
            wait = f"冷却 {cd} 秒，现在能发" if left <= 0 else f"冷却 {cd} 秒，还要等 {self._fmt_wait(left)}"
        yield event.plain_result(
            f"这个会话的自动解析：{here}\n"
            f"{wait}\n"
            "发 /解析 开来开，发 /解析 关 来关。"
        )

    async def terminate(self):
        """插件卸载/停用时释放连接池。"""
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
