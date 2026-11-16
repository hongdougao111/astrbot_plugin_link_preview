# -*- coding: utf-8 -*-
"""不装 AstrBot 也能验证的自测：给 astrbot 打桩，再测解析逻辑。"""
import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _stub():
    a = types.ModuleType("astrbot")
    a1 = types.ModuleType("astrbot.api")
    a1.logger = types.SimpleNamespace(info=print, debug=lambda *_: None,
                                     warning=lambda *x: print("WARN", *x),
                                     error=lambda *x: print("ERR", *x))
    ev = types.ModuleType("astrbot.api.event")

    class _F:
        def command(self, *a, **k):
            def deco(fn):
                return fn
            return deco

        def event_message_type(self, *a, **k):
            def deco(fn):
                return fn
            return deco

        def permission_type(self, *a, **k):
            def deco(fn):
                return fn
            return deco

        class EventMessageType:
            ALL = "all"

        class PermissionType:
            ADMIN = "admin"

    ev.filter = _F()
    ev.AstrMessageEvent = object
    star = types.ModuleType("astrbot.api.star")

    class Star:
        name = "astrbot_plugin_link_preview"

        def __init__(self, context=None):
            self.context = context

    star.Context = object
    star.Star = Star
    mc = types.ModuleType("astrbot.api.message_components")
    mc.Plain = lambda *a, **k: ("plain", a)
    mc.Image = types.SimpleNamespace(fromFileSystem=lambda p: ("img", p))
    mc.Video = types.SimpleNamespace(fromFileSystem=lambda **k: ("video", k.get("path")))
    mc.Video.fromURL = lambda url: ("video-url", url)
    mc.File = lambda **k: ("file", k.get("file"))

    sys.modules["astrbot"] = a
    sys.modules["astrbot.api"] = a1
    sys.modules["astrbot.api.event"] = ev
    sys.modules["astrbot.api.star"] = star
    sys.modules["astrbot.api.message_components"] = mc


_stub()
sys.path.insert(0, str(ROOT))
import main as plugin  # noqa: E402
import resolvers  # noqa: E402

fails = []


def check(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r} want {want!r}")
    else:
        print(f"ok  {name}")


# 1. HTML 解析
html = """<html><head>
<title>傻标题</title>
<meta property="og:title" content="真正的标题 &amp; 副标题">
<meta name="description" content="这是简介，很长很长">
<meta property="og:image" content="/cover.png">
<meta property="og:site_name" content="示例站">
</head><body><meta property="og:title" content="不该被覆盖"></body></html>"""
p = plugin._MetaParser()
p.feed(html)
p.close()
check("og:title 优先", p.meta.get("og:title"), "真正的标题 & 副标题")
check("head 之后不再收", "不该被覆盖" not in p.meta.values(), True)

# 2. 域名匹配
check("子域命中", plugin._domain_ok("www.bilibili.com", ["bilibili.com"]), True)
check("协议前缀能剥", plugin._domain_ok("www.bilibili.com", ["https://bilibili.com/"]), True)
check("不误伤", plugin._domain_ok("notbilibili.com", ["bilibili.com"]), False)
check("空规则不命中", plugin._domain_ok("a.com", []), False)

# 3. URL 提取
pl = plugin.LinkPreview.__new__(plugin.LinkPreview)
pl._last_at = {}
conf = {"max_links": 3, "whitelist": [], "blacklist": ["t.cn"]}
text = "看这个 https://example.com/a?b=1，还有 https://t.cn/abc 和 https://foo.cn/x。"
check("提取并过滤", pl._take_urls(text, conf),
      ["https://example.com/a?b=1", "https://foo.cn/x"])
check("白名单限流", pl._take_urls("https://a.com https://b.com", {"max_links": 2, "whitelist": ["a.com"], "blacklist": []}),
      ["https://a.com"])

# 4. 冷却
conf_cd = {"cooldown": 60}
check("第一次放行", pl._cooling("s1", conf_cd), False)
check("第二次拦住", pl._cooling("s1", conf_cd), True)
check("冷却 0 不拦", pl._cooling("s1", {"cooldown": 0}), False)

# 5. 平台解析器分发
check("B站直链", resolvers.pick("https://www.bilibili.com/video/BV1GJ411x7h7").__name__, "resolve_bilibili")
check("B站短链", resolvers.pick("https://b23.tv/abc").__name__, "resolve_bilibili")
check("网易云", resolvers.pick("https://music.163.com/#/song?id=1").__name__, "resolve_netease")
check("抖音", resolvers.pick("https://v.douyin.com/x/").__name__, "resolve_douyin")
check("无关域名回落", resolvers.pick("https://github.com/a/b"), None)
check("伪装域名不误判", resolvers.pick("https://fakebilibili.com/x"), None)

# 6. B站 ID 抽取
check("BV 号", resolvers.BILI_BV.search("https://www.bilibili.com/video/BV1GJ411x7h7/?p=2").group(1), "BV1GJ411x7h7")
check("av 号", resolvers.BILI_AV.search("https://www.bilibili.com/video/av170001").group(1), "170001")
check("抖音 id", resolvers.DY_VIDEO_ID.search("https://www.douyin.com/video/7298145681699622182").group(1), "7298145681699622182")

# 7. 格式化
check("时长", resolvers._fmt_duration(213), "3:33")
check("时长带时", resolvers._fmt_duration(3725), "1:02:05")
check("播放数", resolvers._fmt_count(110000000), "1.1亿")
check("播放数万", resolvers._fmt_count(12345), "1.2万")
check("图床改 https", resolvers._https("http://i1.hdslb.com/a.jpg"), "https://i1.hdslb.com/a.jpg")
check("协议相对", resolvers._https("//i1.hdslb.com/a.jpg"), "https://i1.hdslb.com/a.jpg")

# 8. 风控中间页识别
check("验证码页识别", resolvers.is_blocked_page("验证码中间页"), True)
check("正常标题不误判", resolvers.is_blocked_page("【官方 MV】Never Gonna Give You Up"), False)
check("cloudflare 页识别", resolvers.is_blocked_page("Just a moment..."), True)

# 9. 消息分段：video 必须独占一条（OneBot retcode 1400 的约束）
async def _seg_check():
    conf = {"download_video": True, "timeout": 25, "max_video_mb": 50, "video_quality": 32,
            "send_image": False, "insecure_ssl": True, "user_agent": "x", "extra_headers": {},
            "max_image_mb": 5, "platform_resolvers": True, "video_send_mode": "video"}
    p = plugin.LinkPreview.__new__(plugin.LinkPreview)
    p._last_at = {}; p._session = None; p._cache_dir = None; p._state = None
    p._schema_defaults = {}
    p.get_config = lambda: dict(conf)
    # 不走网络：直接给一个假媒体路径，验证消息分段逻辑
    import tempfile, os
    fake = os.path.join(tempfile.gettempdir(), "t.mp4")
    open(fake, "wb").write(b"x" * 1024)
    p._download_media = lambda ref, c: asyncio.sleep(0, result=fake)
    p._conf = lambda: dict(conf)
    segs = await p._build_video("https://www.bilibili.com/video/BV1GJ411x7h7", conf)
    if not segs:
        return "None"
    kinds = [[type(x).__name__ if not isinstance(x, tuple) else x[0] for x in s] for s in segs]
    for s in kinds:
        if "video" in s and len(s) > 1:
            return f"video 和别的段混在一条里: {kinds}"
    return "ok" if any("video" in s for s in kinds) else f"没有 video 段: {kinds}"


try:
    check("video 独占一条消息", asyncio.run(_seg_check()), "ok")
except Exception as e:
    check("video 独占一条消息", f"EXC {e}", "ok")

print()
if fails:
    print("FAILED:")
    for f in fails:
        print("  " + f)
    sys.exit(1)
print("全部通过")
