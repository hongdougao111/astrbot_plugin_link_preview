# -*- coding: utf-8 -*-
"""新增平台解析器：GitHub、B站专栏、B站番剧。

只挑接口稳定、无需登录、不涉及签名的做。贴吧/微博/知乎实测都被风控挡住
（403 或安全验证页），做了也是必然失败，所以没加。
"""

from __future__ import annotations

import re

import aiohttp

try:  # 正常作为包的一部分加载
    from .resolvers import (
        Preview,
        _fmt_count,
        _fmt_duration,
        _host_is,
        _https,
        get_json,
    )
except ImportError:  # 自测或独立文件加载时
    from resolvers import (
        Preview,
        _fmt_count,
        _fmt_duration,
        _host_is,
        _https,
        get_json,
    )


# ---------------------------------------------------------------- GitHub

GH_REPO = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:[/?#]|$)")
GH_USER = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/?$")


def match_github(url: str) -> bool:
    return _host_is(urlparse_host(url), "github.com")


def urlparse_host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).hostname or ""


async def resolve_github(session: aiohttp.ClientSession, url: str) -> Preview | None:
    """仓库优先，其次用户主页。Issue / PR / 文件路径不单独解析。"""
    m = GH_REPO.search(url)
    if m:
        owner, repo = m.group(1), m.group(2)
        if repo.endswith(".git"):
            repo = repo[:-4]
        if repo in ("issues", "pulls", "blob", "tree", "releases"):
            return None
        data = await get_json(session, f"https://api.github.com/repos/{owner}/{repo}")
        if not data or "full_name" not in data:
            return None
        bits = []
        if data.get("language"):
            bits.append(data["language"])
        stars = _fmt_count(data.get("stargazers_count"))
        if stars:
            bits.append(f"★ {stars}")
        if data.get("forks_count"):
            bits.append(f"fork {_fmt_count(data['forks_count'])}")
        if data.get("license") and (data["license"] or {}).get("spdx_id"):
            bits.append(data["license"]["spdx_id"])
        return Preview(
            url=data.get("html_url") or url,
            title=data.get("full_name") or f"{owner}/{repo}",
            site="GitHub",
            desc=(data.get("description") or "").strip(),
            image="https://opengraph.githubassets.com/1/" + f"{owner}/{repo}",
            extra=" · ".join(bits),
            kind="link",
        )

    m = GH_USER.search(url)
    if m:
        login = m.group(1)
        data = await get_json(session, f"https://api.github.com/users/{login}")
        if not data or "login" not in data:
            return None
        bits = []
        if data.get("followers"):
            bits.append(f"{_fmt_count(data['followers'])} followers")
        if data.get("public_repos"):
            bits.append(f"{_fmt_count(data['public_repos'])} repos")
        return Preview(
            url=data.get("html_url") or url,
            title=data.get("name") or data.get("login"),
            site="GitHub",
            desc=(data.get("bio") or "").strip(),
            image=data.get("avatar_url") or "",
            extra=" · ".join(bits),
            kind="link",
        )
    return None


# ---------------------------------------------------------------- B 站专栏

BILI_ARTICLE = re.compile(r"bilibili\.com/read/cv(\d+)", re.I)


def match_bili_article(url: str) -> bool:
    return _host_is(urlparse_host(url), "bilibili.com") and bool(BILI_ARTICLE.search(url))


async def resolve_bili_article(
    session: aiohttp.ClientSession, url: str
) -> Preview | None:
    m = BILI_ARTICLE.search(url)
    if not m:
        return None
    aid = m.group(1)
    data = await get_json(
        session,
        f"https://api.bilibili.com/x/article/viewinfo?id={aid}",
        referer="https://www.bilibili.com/",
    )
    if not data or data.get("code") != 0:
        return None
    d = data.get("data") or {}
    if not d.get("title"):
        return None
    bits = []
    if d.get("author_name"):
        bits.append(f"作者：{d['author_name']}")
    stats = d.get("stats") or {}
    views = _fmt_count(stats.get("view"))
    if views:
        bits.append(f"{views}阅读")
    return Preview(
        url=f"https://www.bilibili.com/read/cv{aid}",
        title=d.get("title", ""),
        site="哔哩哔哩专栏",
        desc=(d.get("summary") or "").strip()[:200],
        image=_https(d.get("banner_url") or d.get("image_urls") and (d["image_urls"][0] if d["image_urls"] else "") or ""),
        extra=" · ".join(bits),
        referer="https://www.bilibili.com/",
        kind="link",
    )


# ---------------------------------------------------------------- B 站番剧

BILI_BANGUMI = re.compile(r"bilibili\.com/bangumi/play/(?:ss|ep)(\d+)", re.I)
BILI_SEASON = re.compile(r"bilibili\.com/bangumi/(?:media/)?(?:md|ss)(\d+)", re.I)


def match_bili_bangumi(url: str) -> bool:
    return _host_is(urlparse_host(url), "bilibili.com") and bool(
        BILI_BANGUMI.search(url) or BILI_SEASON.search(url)
    )


async def resolve_bili_bangumi(
    session: aiohttp.ClientSession, url: str
) -> Preview | None:
    season_id = None
    m = BILI_SEASON.search(url)
    if m:
        season_id = m.group(1)
    else:
        m = BILI_BANGUMI.search(url)
        if m:
            # ss 号可以直接当 season_id；ep 号要先查一次
            season_id = m.group(1) if "ss" in url.lower() else None
            if season_id is None:
                ep = await get_json(
                    session,
                    f"https://api.bilibili.com/pgc/view/web/season?ep_id={m.group(1)}",
                    referer="https://www.bilibili.com/",
                )
                if ep and ep.get("code") == 0:
                    season_id = str((ep.get("result") or {}).get("season_id") or "")
    if not season_id:
        return None

    data = await get_json(
        session,
        f"https://api.bilibili.com/pgc/view/web/season?season_id={season_id}",
        referer="https://www.bilibili.com/",
    )
    if not data or data.get("code") != 0:
        return None
    r = data.get("result") or {}
    if not r.get("title"):
        return None

    bits = []
    if r.get("rating") and (r["rating"] or {}).get("score"):
        bits.append(f"评分 {r['rating']['score']}")
    if r.get("new_ep") and (r["new_ep"] or {}).get("desc"):
        bits.append(r["new_ep"]["desc"])
    total = len(r.get("episodes") or [])
    if total:
        bits.append(f"共 {total} 话")
    if r.get("publish") and (r["publish"] or {}).get("pub_time"):
        bits.append(r["publish"]["pub_time"])

    return Preview(
        url=f"https://www.bilibili.com/bangumi/play/ss{season_id}",
        title=r.get("title", ""),
        site="哔哩哔哩番剧",
        desc=(r.get("evaluate") or "").strip()[:200],
        image=_https(r.get("cover") or ""),
        extra=" · ".join(bits),
        referer="https://www.bilibili.com/",
        kind="link",
    )


PLATFORM_RESOLVERS = [
    (match_bili_bangumi, resolve_bili_bangumi),
    (match_bili_article, resolve_bili_article),
    (match_github, resolve_github),
]
