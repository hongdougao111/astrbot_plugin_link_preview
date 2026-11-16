# -*- coding: utf-8 -*-
"""各平台专用解析器。

统一返回 Preview，拿不到就返回 None，让调用方回落到通用 meta。
新增平台只需要写一个函数并登记到 RESOLVERS 里。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import parse_qs, urlparse

import aiohttp

PC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"
)


@dataclass
class Preview:
    """一条解析结果。字段全部给默认值，方便各平台只填自己有的。"""

    url: str
    title: str
    site: str = ""
    desc: str = ""
    image: str = ""
    extra: str = ""          # 附加的一行：UP 主 / 歌手 / 播放量之类
    referer: str = ""        # 下载封面图时要带的 Referer，防盗链靠它
    kind: str = "link"       # link / video / music


# ---------------------------------------------------------------- 工具

async def resolve_short_url(session: aiohttp.ClientSession, url: str, ua: str = PC_UA) -> str:
    """跟一次跳转拿真实地址；失败就原样返回。"""
    try:
        async with session.get(url, headers={"User-Agent": ua}, allow_redirects=True) as resp:
            return str(resp.url) or url
    except Exception:
        return url


async def get_json(session: aiohttp.ClientSession, url: str, referer: str = "") -> dict | None:
    headers = {"User-Agent": PC_UA, "Accept": "application/json, text/plain, */*"}
    if referer:
        headers["Referer"] = referer
    try:
        async with session.get(url, headers=headers, allow_redirects=True) as resp:
            if resp.status >= 400:
                return None
            return json.loads(await resp.read())
    except Exception:
        return None


def _fmt_duration(sec) -> str:
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return ""
    if sec <= 0:
        return ""
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_count(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    if n >= 100000000:
        return f"{n / 100000000:.1f}亿"
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)


def _https(url: str) -> str:
    """B 站图床给的是 http，改成 https 才不会被平台拦。"""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://"):
        return "https://" + url[7:]
    return url


# ---------------------------------------------------------------- B 站

BILI_BV = re.compile(r"(BV[0-9A-Za-z]{10})")
BILI_AV = re.compile(r"/av(\d+)", re.IGNORECASE)


def _host_is(host: str, *domains: str) -> bool:
    """精确匹配域名或其子域。用 endswith("bilibili.com") 会放过 fakebilibili.com。"""
    host = (host or "").lower().strip(".")
    for d in domains:
        d = d.lower()
        if host == d or host.endswith("." + d):
            return True
    return False


def _match_bilibili(url: str) -> bool:
    return _host_is(urlparse(url).hostname or "", "bilibili.com", "b23.tv", "bili2233.cn")


async def resolve_bilibili(session: aiohttp.ClientSession, url: str) -> Preview | None:
    real = url
    host = (urlparse(url).hostname or "").lower()
    if host in ("b23.tv", "bili2233.cn"):
        real = await resolve_short_url(session, url)

    api = ""
    m = BILI_BV.search(real)
    if m:
        api = f"https://api.bilibili.com/x/web-interface/view?bvid={m.group(1)}"
    else:
        m = BILI_AV.search(real)
        if m:
            api = f"https://api.bilibili.com/x/web-interface/view?aid={m.group(1)}"
    if not api:
        return None

    data = await get_json(session, api, referer="https://www.bilibili.com/")
    if not data or data.get("code") != 0:
        return None
    d = data.get("data") or {}
    if not d.get("title"):
        return None

    owner = (d.get("owner") or {}).get("name", "")
    stat = d.get("stat") or {}
    bits = [f"UP主：{owner}"] if owner else []
    dur = _fmt_duration(d.get("duration"))
    if dur:
        bits.append(f"时长 {dur}")
    views = _fmt_count(stat.get("view"))
    if views:
        bits.append(f"{views}播放")

    desc = (d.get("desc") or "").strip()
    if desc == "-":
        desc = ""

    return Preview(
        url=f"https://www.bilibili.com/video/{d.get('bvid') or ''}".rstrip("/"),
        title=d.get("title", ""),
        site="哔哩哔哩",
        desc=desc,
        image=_https(d.get("pic") or ""),
        extra=" · ".join(bits),
        referer="https://www.bilibili.com/",
        kind="video",
    )


# ---------------------------------------------------------------- 网易云

NE_SONG = re.compile(r"[?&#]id=(\d+)")
NE_SHORT = ("163cn.tv",)


# 对外别名：main.py 要判断"这条链接要不要走下载流程"
match_bilibili = _match_bilibili


def _match_netease(url: str) -> bool:
    return _host_is(urlparse(url).hostname or "", "music.163.com", *NE_SHORT)


async def resolve_netease(session: aiohttp.ClientSession, url: str) -> Preview | None:
    real = url
    host = (urlparse(url).hostname or "").lower()
    if host in NE_SHORT:
        real = await resolve_short_url(session, url)
        host = (urlparse(real).hostname or "").lower()
    if not _host_is(host, "music.163.com"):
        return None

    m = NE_SONG.search(real)
    if not m:
        return None
    song_id = m.group(1)

    data = await get_json(
        session,
        f"https://music.163.com/api/song/detail?ids=[{song_id}]",
        referer="https://music.163.com/",
    )
    songs = (data or {}).get("songs") or []
    if not songs:
        return None
    sg = songs[0]
    album = sg.get("album") or {}
    artists = "、".join(a.get("name", "") for a in (sg.get("artists") or []) if a.get("name"))
    bits = []
    if artists:
        bits.append(artists)
    if album.get("name"):
        bits.append(f"《{album['name']}》")
    dur = _fmt_duration((sg.get("duration") or 0) // 1000)
    if dur:
        bits.append(dur)

    return Preview(
        url=f"https://music.163.com/#/song?id={song_id}",
        title=sg.get("name") or "",
        site="网易云音乐",
        desc="",
        image=_https(album.get("picUrl") or ""),
        extra=" · ".join(bits),
        referer="https://music.163.com/",
        kind="music",
    )


# ---------------------------------------------------------------- 抖音

DY_VIDEO_ID = re.compile(r"/(?:video|note)/(\d{6,})")


def _match_douyin(url: str) -> bool:
    return _host_is(urlparse(url).hostname or "", "douyin.com", "iesdouyin.com")


async def resolve_douyin(
    session: aiohttp.ClientSession, url: str, cookie: str = ""
) -> Preview | None:
    """抖音分享页在无 Cookie 时只下发页面壳，_ROUTER_DATA 里经常没有 item_list，
    甚至直接给一个验证码中间页。能拿到就拿，拿不到返回 None 让调用方回落通用 meta。

    cookie 参数留给用户在配置里贴上自己的抖音 Cookie —— 这是唯一稳定拿到数据的办法，
    插件本身不做签名算法（那要随抖音前端一起变，维护不起）。
    """
    real = await resolve_short_url(session, url, ua=MOBILE_UA)
    m = DY_VIDEO_ID.search(real)
    if not m:
        return None
    vid = m.group(1)

    share = f"https://www.iesdouyin.com/share/video/{vid}/"
    headers = {"User-Agent": MOBILE_UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    if cookie:
        headers["Cookie"] = cookie
    try:
        async with session.get(share, headers=headers, allow_redirects=True) as resp:
            text = (await resp.read()).decode("utf-8", "replace")
    except Exception:
        return None

    idx = text.find("_ROUTER_DATA")
    if idx < 0:
        return None
    eq = text.find("=", idx)
    if eq < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(text[eq + 1:].lstrip())
    except ValueError:
        return None

    loader = data.get("loaderData") or {}
    item = None
    for value in loader.values():
        if not isinstance(value, dict):
            continue
        res = value.get("videoInfoRes")
        if isinstance(res, dict):
            items = res.get("item_list") or []
            if items:
                item = items[0]
                break
    if not item:
        return None

    video = item.get("video") or {}
    cover = ""
    cov = video.get("cover") or video.get("origin_cover") or {}
    if isinstance(cov, dict):
        urls = cov.get("url_list") or []
        if urls:
            cover = urls[0]
    elif isinstance(cov, str):
        cover = cov

    author = (item.get("author") or {}).get("nickname", "")
    stats = item.get("statistics") or {}
    bits = []
    if author:
        bits.append(f"@{author}")
    likes = _fmt_count(stats.get("digg_count"))
    if likes:
        bits.append(f"{likes}赞")
    dur = _fmt_duration((video.get("duration") or 0) // 1000 if video.get("duration") else 0)
    if dur:
        bits.append(dur)

    desc = (item.get("desc") or "").strip()
    return Preview(
        url=f"https://www.douyin.com/video/{vid}",
        title=desc.split("\n")[0][:60] or "抖音视频",
        site="抖音",
        desc=desc[:200],
        image=_https(cover),
        extra=" · ".join(bits),
        referer="https://www.douyin.com/",
        kind="video",
    )


# ---------------------------------------------------------------- 媒体直链

@dataclass
class MediaRef:
    """一个可以直接下载的媒体地址。"""

    url: str
    referer: str = ""
    size: int = 0          # 服务端报的字节数，0 表示未知
    ext: str = ".mp4"
    kind: str = "video"    # video / audio
    # 缓存用的稳定标识。B 站直链每次请求都带不同的签名参数，拿 URL 做 key
    # 会导致同一个视频反复下载，所以用 bvid + 清晰度。
    cache_key: str = ""


async def bilibili_stream(
    session: aiohttp.ClientSession, url: str, qn: int = 32
) -> tuple[MediaRef, Preview] | None:
    """拿 B 站的视频直链。

    qn: 16=360P, 32=480P, 64=720P, 80=1080P。不带 Cookie 时 720P 是天花板。
    fnval=1 走 durl 合并流（音视频已经并好，能直接发），fnval=16 是 dash 分离流，
    还得自己合流，QQ 群发不出去，所以这里只用 durl。
    """
    real = url
    if _host_is(urlparse(url).hostname or "", "b23.tv", "bili2233.cn"):
        real = await resolve_short_url(session, url)

    api = ""
    m = BILI_BV.search(real)
    if m:
        api = f"https://api.bilibili.com/x/web-interface/view?bvid={m.group(1)}"
    else:
        m = BILI_AV.search(real)
        if m:
            api = f"https://api.bilibili.com/x/web-interface/view?aid={m.group(1)}"
    if not api:
        return None

    data = await get_json(session, api, referer="https://www.bilibili.com/")
    if not data or data.get("code") != 0:
        return None
    d = data.get("data") or {}
    cid = d.get("cid")
    bvid = d.get("bvid")
    if not cid or not bvid:
        return None

    play = await get_json(
        session,
        f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}"
        f"&qn={qn}&fnval=1&platform=html5&high_quality=1",
        referer="https://www.bilibili.com/",
    )
    if not play or play.get("code") != 0:
        return None
    pd = play.get("data") or {}
    durls = pd.get("durl") or []
    if not durls:
        return None
    first = durls[0]

    owner = (d.get("owner") or {}).get("name", "")
    stat = d.get("stat") or {}
    bits = [f"UP主：{owner}"] if owner else []
    dur = _fmt_duration(d.get("duration"))
    if dur:
        bits.append(f"时长 {dur}")

    preview = Preview(
        url=f"https://www.bilibili.com/video/{bvid}",
        title=d.get("title", ""),
        site="哔哩哔哩",
        desc=(d.get("desc") or "").strip().replace("-", ""),
        image=_https(d.get("pic") or ""),
        extra=" · ".join(bits),
        referer="https://www.bilibili.com/",
        kind="video",
    )
    return (
        MediaRef(
            url=first.get("url", ""),
            referer="https://www.bilibili.com/",
            size=int(first.get("size") or 0),
            ext=".mp4",
            kind="video",
            cache_key=f"bili_{bvid}_q{qn}",
        ),
        preview,
    )


# ---------------------------------------------------------------- 登记表

RESOLVERS: list[tuple[Callable[[str], bool], Callable[..., Awaitable[Preview | None]]]] = [
    (_match_bilibili, resolve_bilibili),
    (_match_netease, resolve_netease),
    (_match_douyin, resolve_douyin),
]

# 这些标题说明抓到的是风控中间页，不是真内容，不能当解析结果发出去
BLOCKED_TITLES = ("验证码中间页", "安全验证", "环境异常", "Please verify", "Just a moment")


def pick(url: str):
    """按域名挑一个专用解析器，没有就返回 None。"""
    for matcher, fn in RESOLVERS:
        try:
            if matcher(url):
                return fn
        except Exception:
            continue
    return None


def is_blocked_page(title: str) -> bool:
    """页面标题像风控中间页就判定为没拿到真内容。"""
    t = (title or "").strip()
    return any(k in t for k in BLOCKED_TITLES)
