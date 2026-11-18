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
    mc.Record = lambda **k: ("record", k.get("file"))

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
# 剩余时间与格式化
pl._last_at = {}
_pl2 = plugin.LinkPreview.__new__(plugin.LinkPreview)
_pl2._last_at = {}; _pl2._hint_at = {}
check("首次能发", _pl2._cooldown_left("x", {"cooldown": 10}), 0)
left = _pl2._cooldown_left("x", {"cooldown": 10})
check("立刻再发要等", 1 <= left <= 10, True)
check("格式化秒", plugin.LinkPreview._fmt_wait(45), "45 秒")
check("格式化分秒", plugin.LinkPreview._fmt_wait(125), "2 分 5 秒")
check("格式化整分", plugin.LinkPreview._fmt_wait(120), "2 分钟")
check("提示节流第一次", _pl2._hint_once("x"), True)
check("提示节流第二次被压", _pl2._hint_once("x"), False)

# 5. 平台解析器分发
check("B站直链", resolvers.pick("https://www.bilibili.com/video/BV1GJ411x7h7").__name__, "resolve_bilibili")
check("B站短链", resolvers.pick("https://b23.tv/abc").__name__, "resolve_bilibili")
check("网易云", resolvers.pick("https://music.163.com/#/song?id=1").__name__, "resolve_netease")
check("抖音已移除", resolvers.pick("https://v.douyin.com/x/"), None)
check("无关域名回落", resolvers.pick("https://github.com/a/b"), None)
check("伪装域名不误判", resolvers.pick("https://fakebilibili.com/x"), None)

# 6. B站 ID 抽取
check("BV 号", resolvers.BILI_BV.search("https://www.bilibili.com/video/BV1GJ411x7h7/?p=2").group(1), "BV1GJ411x7h7")
check("av 号", resolvers.BILI_AV.search("https://www.bilibili.com/video/av170001").group(1), "170001")
# 抖音解析已删除，DY_VIDEO_ID 不该再存在
check("抖音正则已移除", hasattr(resolvers, "DY_VIDEO_ID"), False)

# 点歌：song_summary 的字段压缩
_s = resolvers.song_summary({
    "id": 1, "name": "测试", "duration": 213000,
    "artists": [{"name": "A"}, {"name": "B"}],
    "album": {"name": "专辑", "picUrl": "http://p1.music.126.net/x.jpg"},
})
check("song_summary 歌手拼接", _s["artists"], "A、B")
check("song_summary 时长转秒", _s["duration"], 213)
check("song_summary 封面升 https", _s["cover"].startswith("https://"), True)

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

# 8.5 小程序卡片 URL 提取
_p2 = plugin.LinkPreview.__new__(plugin.LinkPreview)
_p2._last_at = {}
_card_mini = {
    "app": "com.tencent.miniapp_01",
    "meta": {
        "detail_1": {
            "appid": "1109937557",
            "title": "哔哩哔哩",
            "desc": "点击查看",
            "qqdocurl": "https://b23.tv/DPBqgs",
            "preview": "https://pic.example.com/a.jpg",
        }
    },
}
check("小程序 qqdocurl", _p2._urls_from_card(_card_mini)[0], "https://b23.tv/DPBqgs")
_card_news = {"app": "com.tencent.structmsg", "meta": {"news": {"jumpUrl": "https://example.com/x", "title": "t"}}}
check("structmsg jumpUrl", _p2._urls_from_card(_card_news)[0], "https://example.com/x")
check("深层嵌套也能挖", _p2._urls_from_card({"a": {"b": [{"c": {"jumpUrl": "https://deep.cn/y"}}]}})[0], "https://deep.cn/y")
check("空卡片返回空", _p2._urls_from_card({"app": "x"}), [])
# 双层 data（OneBot json 段常见：data.data 还是 JSON 字符串）
check("双层 data 也能挖", _p2._urls_from_card({"data": '{"meta":{"detail_1":{"qqdocurl":"https://b23.tv/xyz"}}}'})[0],
      "https://b23.tv/xyz")

# 8.6 下载提示文案
_p3 = plugin.LinkPreview.__new__(plugin.LinkPreview)
_p3._last_at = {}; _p3._hint_at = {}
_prev = resolvers.Preview(url="u", title="测试视频")
_ref = resolvers.MediaRef(url="x", size=12 * 1024 * 1024)
check("默认提示含清晰度", "480P" in _p3._download_notice(_prev, _ref, {"video_quality": 32}), True)
check("默认提示含大小", "12 MB" in _p3._download_notice(_prev, _ref, {"video_quality": 32}), True)
check("360P 标签", _p3._quality_label(16), "360P")
check("720P 标签", _p3._quality_label(64), "720P")
check("未知清晰度", _p3._quality_label(999), "999")
check("自定义模板", _p3._download_notice(_prev, _ref,
      {"video_quality": 32, "download_notice": "在下了：{title} {quality}"}), "在下了：测试视频 480P")
check("坏模板不炸", "480P" in _p3._download_notice(_prev, _ref,
      {"video_quality": 32, "download_notice": "{不存在}"}), True)
check("大小未知时不写", "约" in _p3._download_notice(_prev, resolvers.MediaRef(url="x", size=0), {"video_quality": 32}), False)

# 8.7 XML 卡片（Lagrange / 老版 go-cqhttp 下发，上游 ComponentTypes 没有 xml 类型）
_p4 = plugin.LinkPreview.__new__(plugin.LinkPreview)
_p4._last_at = {}
_xml_attr = '<msg serviceID="1" url="https://b23.tv/AbCdEf" brief="哔哩哔哩"/>'
_xml_tag = "<msg><item><qqdocurl>https://www.bilibili.com/video/BV1xx411c7mD</qqdocurl></item></msg>"
check("XML 属性式", _p4._urls_from_xml(_xml_attr), ["https://b23.tv/AbCdEf"])
check("XML 标签式", _p4._urls_from_xml(_xml_tag), ["https://www.bilibili.com/video/BV1xx411c7mD"])
check("XML 转义还原", _p4._urls_from_xml('<msg url="https://a.cn/x?p=1&amp;t=2"/>'), ["https://a.cn/x?p=1&t=2"])
check("XML 无关不误报", _p4._urls_from_xml("<msg serviceID='1'/>"), [])


class _Raw:
    def __init__(self, message):
        self.message = message


class _MO:
    def __init__(self, chain, raw):
        self.message = chain
        self.raw_message = raw


class _Ev:
    def __init__(self, chain, raw):
        self.message_obj = _MO(chain, raw) if raw is not None else None


check("raw_message 兜底（xml 段被上游丢掉）",
      _p4._scan_raw_message(_Ev([], _Raw([{"type": "xml", "data": {"xml": _xml_attr}}]))),
      ["https://b23.tv/AbCdEf"])
check("raw 是 dict 形式",
      _p4._scan_raw_message(_Ev([], _Raw({"message": [{"type": "xml", "data": {"xml": _xml_tag}}]}))),
      ["https://www.bilibili.com/video/BV1xx411c7mD"])
check("CQ 码字符串形式",
      _p4._scan_raw_message(_Ev([], _Raw("[CQ:xml,data=&lt;msg url=&quot;https://b23.tv/CQ&quot;/&gt;]"))),
      ["https://b23.tv/CQ"])
check("没有 message_obj 不炸", _p4._scan_raw_message(_Ev([], None)), [])

# 8.8 暴力兜底扫描（卡片藏在任何地方都能挖出来）
_p5 = plugin.LinkPreview.__new__(plugin.LinkPreview)
_p5._last_at = {}
_BILI = "https://www.bilibili.com/video/BV1GJ411x7h7"


def _mkraw(**kw):
    return types.SimpleNamespace(**kw)


check("噪音域名不认作内容", _p5._is_content_url("https://q1.qlogo.cn/g?b=qq"), False)
check("图床不认作内容", _p5._is_content_url("https://i0.hdslb.com/x.jpg"), False)
check("B站视频认作内容", _p5._is_content_url(_BILI), True)

# 藏在一个奇怪属性名里
_ev = _mkraw(message_obj=_mkraw(message=[], raw_message=_mkraw(message="", prompt=f"[卡片] {_BILI}")))
check("任意属性里的链接", _p5._scan_everything(_ev), [_BILI])

# JSON 转义写法 https:\/\/
_esc = _BILI.replace("/", "\\/")
_ev2 = _mkraw(message_obj=_mkraw(message=[], raw_message=_mkraw(message=[{"type": "xml", "data": {"xml": _esc}}])))
check("反斜杠转义能还原", _p5._scan_everything(_ev2), [_BILI])

# 深层嵌套
_ev3 = _mkraw(message_obj=_mkraw(message=[], raw_message={"a": {"b": {"c": [{"d": _BILI}]}}}))
check("深层嵌套 dict", _p5._scan_everything(_ev3), [_BILI])

# 噪音和内容混在一起，只留内容
_ev4 = _mkraw(message_obj=_mkraw(message=[], raw_message=_mkraw(message=f"https://q1.qlogo.cn/x.jpg {_BILI} https://gtimg.cn/y.png")))
check("过滤噪音保留内容", _p5._scan_everything(_ev4), [_BILI])

# 循环引用不能死循环
class _Loop:
    pass


_lp = _Loop()
_lp.self_ref = _lp
_lp.msg = "https://example.com/a"
check("循环引用不卡死", _p5._scan_everything(_mkraw(message_obj=_mkraw(message=[], raw_message=_lp))),
      ["https://example.com/a"])

# 8.9 卡片缓存（卡片和诊断指令是两条消息）
_p6 = plugin.LinkPreview.__new__(plugin.LinkPreview)
_p6._last_at = {}; _p6._hint_at = {}; _p6._recent_card = {}
_SID = "aiocqhttp:GroupMessage:9"
_card_obj = {
    "app": "com.tencent.miniapp_01",
    "prompt": "[QQ小程序]哔哩哔哩",
    "meta": {"detail_1": {"qqdocurl": _BILI, "title": "哔哩哔哩"}},
}


class _C:
    def __init__(self, t, **kw):
        self.type = t
        for k, v in kw.items():
            setattr(self, k, v)


_ev_card = types.SimpleNamespace(
    message_str="", unified_msg_origin=_SID,
    message_obj=types.SimpleNamespace(message=[_C("Json", data=_card_obj)], raw_message=None))
_p6._remember_card(_ev_card)
check("卡片进缓存", len(_p6._recent_card.get(_SID, {}).get("cards", [])), 1)

_ev_plain = types.SimpleNamespace(
    message_str="/链接诊断", unified_msg_origin=_SID,
    message_obj=types.SimpleNamespace(message=[_C("Plain", text="/链接诊断")], raw_message=None))
_desc = _p6._describe_event(_ev_plain)
check("诊断能看到缓存的卡片", _BILI in _desc, True)
check("诊断标明是缓存", "最近一条卡片" in _desc, True)

# 引用消息里的卡片
_ev_reply = types.SimpleNamespace(
    message_str="/链接诊断", unified_msg_origin=_SID,
    message_obj=types.SimpleNamespace(
        message=[_C("Reply", id="1", chain=[_C("Json", data=_card_obj)])], raw_message=None))
check("引用消息里的卡片", _BILI in _p6._describe_event(_ev_reply), True)

# 没收到过卡片的群
_ev_empty = types.SimpleNamespace(
    message_str="/链接诊断", unified_msg_origin="aiocqhttp:GroupMessage:other",
    message_obj=types.SimpleNamespace(message=[_C("Plain", text="x")], raw_message=None))
check("没卡片时如实说", "还没收到过卡片" in _p6._describe_event(_ev_empty), True)

# 8.10 卡片五种分支（对齐 astrbot_plugin_multi_parser 的 ShareCardExtractor）
_p7 = plugin.LinkPreview.__new__(plugin.LinkPreview)
_p7._last_at = {}
for _name, _card in {
    "detail_1.qqdocurl": {"meta": {"detail_1": {"qqdocurl": _BILI}}},
    "news.jumpUrl": {"meta": {"news": {"jumpUrl": _BILI}}},
    "miniapp.pcJumpUrl": {"meta": {"miniapp": {"pcJumpUrl": _BILI}}},
    "miniapp.legacyUrl": {"meta": {"miniapp": {"legacyUrl": _BILI}}},
    "feed.jumpUrl": {"meta": {"feed": {"jumpUrl": _BILI}}},
}.items():
    check(f"卡片分支 {_name}", _p7._urls_from_card(_card), [_BILI])

# raw_message 的 message 段是组件对象（不是 dict）—— 这条以前是漏的
_comp_card = {"meta": {"detail_1": {"qqdocurl": _BILI}}}
_ev_obj = types.SimpleNamespace(
    message_obj=types.SimpleNamespace(
        message=[], raw_message=types.SimpleNamespace(message=[_C("Json", data=_comp_card)])))
check("raw 段是组件对象", _p7._scan_raw_message(_ev_obj), [_BILI])

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
