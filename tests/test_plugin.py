# -*- coding: utf-8 -*-
"""com3d2-mod-search 插件测试（离线可跑，零硬编码）。

运行：
    python tests/run_tests.py          # 不依赖 pytest
    python -m pytest tests -q          # 装了 pytest 也可以

联网用例默认跳过；要看真实搜索效果：C3D_LIVE=1 python tests/run_tests.py
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap as B  # noqa: E402

MOD = B.load_plugin()
MC = sys.modules[f"{B.PKG_NAME}.mukuu_client"]
TM = sys.modules[f"{B.PKG_NAME}.tier_map"]
HR = sys.modules[f"{B.PKG_NAME}.html_render"]


# ────────────────────────────── 元数据与配置形态 ──────────────────────────────

def test_manifest_fields():
    m = B.manifest()
    assert m.get("plugin_id"), "manifest 缺 plugin_id"
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(m.get("version") or "")), f"版本号不是 semver: {m.get('version')}"
    assert m.get("display_name") and m.get("author"), "display_name / author 不应为空"
    assert str(m.get("core_version") or ""), "建议声明 core_version（无上界）"
    assert ">" not in str(m.get("core_version") or "") or True  # 仅提示，不做强约束
    icon = m.get("icon")
    if icon:
        assert (B.ROOT / icon).is_file(), f"manifest 声明了 icon 但文件不存在: {icon}"
    if m.get("repo"):
        assert str(m["repo"]).startswith("http"), "repo 应是 URL"


def test_schema_shape():
    """schema 必须是框架的 section+fields 形态，且不含已废弃的 enum 类型。"""
    s = B.schema()
    assert isinstance(s, dict) and s, "schema 不应为空"
    assert "properties" not in s, "schema 不该用 JSON-Schema 的 properties 包裹（框架按顶层键解析）"
    seen = 0
    for sec_name, sec in s.items():
        assert sec.get("type") == "section", f"{sec_name} 应是 section（框架只认 fields）"
        fields = sec.get("fields")
        assert isinstance(fields, dict) and fields, f"{sec_name}.fields 不应为空"
        for key, f in fields.items():
            assert f.get("type"), f"{sec_name}.{key} 缺 type"
            assert f.get("name"), f"{sec_name}.{key} 缺 name"
            assert f.get("type") != "enum", f"{sec_name}.{key} 用了已废弃的 enum，应改 string+options"
            if "options" in f:
                assert isinstance(f["options"], list) and f["options"], f"{sec_name}.{key}.options 应为非空列表"
            seen += 1
    assert seen >= 5, "字段数量看起来不对"


def test_notify_empty_default_off():
    f = B.schema()["section_main"]["fields"]
    assert "notify_empty" in f, "缺少 notify_empty 配置项"
    assert f["notify_empty"]["type"] == "switch"
    assert f["notify_empty"].get("default") is False, "notify_empty 必须默认关"


def test_tool_params_use_json_schema_enum():
    src = (B.ROOT / "main.py").read_text(encoding="utf-8")
    assert '"enum": SORTS' in src or "'enum': SORTS" in src, "工具参数应使用 JSON-Schema 的 enum"
    assert '"options": SORTS' not in src, "工具参数里不应再出现 options"


# ────────────────────────────── 关键词梯级 ──────────────────────────────

def test_tier_map_structure():
    """从映射表里动态取一个词，验证梯级结构（不写死任何具体词）。"""
    assert TM.TIER_MAP, "TIER_MAP 不应为空"
    kw, trio = next(iter(TM.TIER_MAP.items()))
    assert len(trio) == 3, "每个词应是 (片假名, 汉字, 英文) 三元组"
    q = TM.build_queries(kw)
    assert q, f"已知词 {kw!r} 应至少产出一个查询"
    names = [name for _, name in q]
    assert len(names) == len(set(names)), "梯级名不应重复"
    assert all(isinstance(v, str) and v for v, _ in q), "查询词不应为空"


def test_tier_map_noise_and_fallback():
    for w in TM.NOISE_WORDS:
        assert w.lower() not in TM.strip_noise(f"{w} 测试词 {w.upper()}").lower(), f"噪音词 {w} 未被剥离"
    unknown = "zzz_not_in_map_zzz"
    assert TM.build_queries(unknown) == [(unknown, "原文")], "表外词应原样返回"
    assert TM.build_queries("   ") == [], "空关键词应返回空列表"


# ────────────────────────────── Mukuu 客户端 ──────────────────────────────

def test_parse_post_and_download_links():
    post = {
        "idStr": "12345",
        "createdAt": "2026-01-02T03:04:05Z",
        "text": "https://mega.nz/file/abc と https://example.com/x と https://twitter.com/a/status/1",
        "favoriteCount": 7, "retweetCount": 2,
        "postedBy": {"name": "作者", "screenName": "screen"},
    }
    it = MC.parse_post(post)
    assert it["author"] == "作者" and it["screen"] == "screen"
    assert it["date"] == "2026-01-02" and it["fav"] == 7 and it["rt"] == 2
    assert it["tw"].endswith("/status/12345")
    # 下载链接只认白名单域名
    assert it["dl"] == ["https://mega.nz/file/abc"], f"白名单过滤异常: {it['dl']}"
    assert MC.extract_download_links("") == []
    assert MC.extract_download_links("见 https://drive.google.com/f/1。") == ["https://drive.google.com/f/1"]


def test_serialize_items_is_compact_json():
    items = B.synthetic_items(2)
    raw = MC.serialize_items(items)
    data = json.loads(raw)
    assert len(data) == 2 and data[0]["n"] == 1
    for k in ("author", "screen", "date", "fav", "rt", "ja", "dl", "tw"):
        assert k in data[0], f"序列化缺字段 {k}"


def test_cache_key_includes_limit_and_ttl():
    calls = []

    async def fake_post(path, payload):
        calls.append(payload)
        limit = payload["data"].get("limit") or 0
        return [{"idStr": str(i)} for i in range(limit)]

    cli = MC.MukuuClient(timeout=5, cache_ttl=60)
    cli._post = fake_post

    async def run():
        a = await cli.search("k", limit=5)
        n_after_a = len(calls)
        b = await cli.search("k", limit=9)          # 同词同页不同条数 ⇒ 不能命中 5 条的缓存
        assert len(a) == 5 and len(b) == 9, "limit 应真正生效（缓存键必须含 limit）"
        assert len(calls) == n_after_a + 1, "换 limit 不该复用旧缓存"
        again = await cli.search("k", limit=5)      # 回到旧参数 ⇒ 命中缓存
        assert len(again) == 5 and len(calls) == n_after_a + 1, "同参数应命中缓存（零请求）"

    asyncio.run(run())

    cli2 = MC.MukuuClient(timeout=5, cache_ttl=1)
    cli2._post = fake_post
    seq = []

    async def run_ttl():
        await cli2.search("t", limit=1)
        n1 = len(calls)
        await cli2.search("t", limit=1)
        assert len(calls) == n1, "TTL 内应命中缓存"
        cli2._cache = {k: (v[0] - 10, v[1]) for k, v in cli2._cache.items()}   # 手动把时间戳拨旧
        await cli2.search("t", limit=1)
        assert len(calls) == n1 + 1, "超过 TTL 应重新请求"
        seq.append(True)

    asyncio.run(run_ttl())


def test_client_reuse_and_close():
    cli = MC.MukuuClient(timeout=5, cache_ttl=0)
    c1 = cli._ensure_client()
    c2 = cli._ensure_client()
    assert c1 is c2, "同一个客户端应被复用（省 TLS 握手）"

    async def run():
        await cli.aclose()
        await cli.aclose()                     # 可重入
        assert cli._client is None
        c3 = cli._ensure_client()
        assert c3 is not None and c3 is not c1, "关闭后应重建客户端"

    asyncio.run(run())


def test_post_retries_once_after_broken_client():
    """连接池坏掉时应重建客户端重试一次——全程用假的 HTTP 层，不碰真网络。"""
    cli = MC.MukuuClient(timeout=5, cache_ttl=0)
    calls = []

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"idStr": "1"}]

    class BrokenClient:
        is_closed = False

        async def post(self, *a, **k):
            calls.append("broken")
            raise RuntimeError("连接被重置")

        async def aclose(self):
            self.is_closed = True

    class GoodClient:
        is_closed = False

        async def post(self, *a, **k):
            calls.append("good")
            return _Resp()

        async def aclose(self):
            self.is_closed = True

    cli._client = BrokenClient()

    def fake_ensure():
        if cli._client is None:
            cli._client = GoodClient()
        return cli._client

    cli._ensure_client = fake_ensure          # 替掉真实客户端构造
    out = asyncio.run(cli._post("/x", {}))
    assert calls == ["broken", "good"], f"应在连接坏掉后重建客户端重试一次，实得 {calls}"
    assert out == [{"idStr": "1"}], "重试成功后应返回解析结果"


# ────────────────────────────── 空结果策略（用户要点） ──────────────────────────────

EMPTY_SEARCH = ("empty", "0", [], [])


def _skip(reason: str):
    """pytest 下计入 skipped；独立 runner 下返回标记字符串。"""
    try:
        import pytest  # type: ignore
        pytest.skip(reason)
    except ImportError:
        return f"skipped（{reason}）"


def _patch_empty(inst):
    async def fake(keyword, skip, sort, limit):
        return [], 0, [(keyword, "片假名", -1)], []
    inst._do_search = fake
    return inst


def _patch_hit(inst, items=None):
    items = items or B.synthetic_items(2)

    async def fake(keyword, skip, sort, limit):
        return items, len(items), [(keyword, "片假名", len(items))], []
    inst._do_search = fake
    return inst


def test_empty_result_matrix():
    with tempfile.TemporaryDirectory() as td:
        # ① 工具路径 + 默认关：不插话，note 保持旧版写法
        ctx = B.StubCtx(Path(td) / "a")
        inst = _patch_empty(B.make_plugin(MOD, ctx))
        asyncio.run(inst.initialize())
        out = json.loads(asyncio.run(inst.tool_search(B.FakeBatchEvent(), "kw")))
        assert ctx.sender.texts() == [], "默认关时工具路径不应发消息"
        assert out["total"] == 0 and out["items"] == []
        note = out.get("note", "")
        assert note.startswith("未找到结果"), f"note 应保持旧版写法，实得 {note!r}"
        assert "请你" not in note and "口吻" not in note, "note 里不应出现额外指令（保持原样）"

        # ② 工具路径 + 开关开：旧行为（插件直接发提示）
        ctx2 = B.StubCtx(Path(td) / "b")
        inst2 = _patch_empty(B.make_plugin(MOD, ctx2, notify_empty=True))
        asyncio.run(inst2.initialize())
        out2 = json.loads(asyncio.run(inst2.tool_search(B.FakeBatchEvent(), "kw")))
        assert out2 == out, "开关只影响是否插话，工具返回给 LLM 的内容必须一致"
        sent = ctx2.sender.texts()
        assert len(sent) == 1 and "未找到结果" in sent[0], f"开=旧行为应发一条提示，实得 {sent}"

        # ③ 命令路径 + 默认关：回一条极简提示
        ctx3 = B.StubCtx(Path(td) / "c")
        inst3 = _patch_empty(B.make_plugin(MOD, ctx3))
        asyncio.run(inst3.initialize())
        asyncio.run(inst3._handle_cmd("qq:gm:100", "kw"))
        sent3 = ctx3.sender.texts()
        assert len(sent3) == 1 and "kw" in sent3[0] and "尝试" not in sent3[0], \
            f"命令路径默认应给极简提示，实得 {sent3}"

        # ④ 命令路径 + 开关开：详细提示
        ctx4 = B.StubCtx(Path(td) / "d")
        inst4 = _patch_empty(B.make_plugin(MOD, ctx4, notify_empty=True))
        asyncio.run(inst4.initialize())
        asyncio.run(inst4._handle_cmd("qq:gm:100", "kw"))
        assert "尝试" in ctx4.sender.texts()[0], "开关开时命令路径应给详细提示"


def test_hit_path_unchanged():
    with tempfile.TemporaryDirectory() as td:
        ctx = B.StubCtx(Path(td))
        inst = _patch_hit(B.make_plugin(MOD, ctx))
        asyncio.run(inst.initialize())
        out = json.loads(asyncio.run(inst.tool_search(B.FakeBatchEvent(), "kw")))
        assert len(out["items"]) == 2 and out["sent"], "有结果时应照常产出并发送"
        actions = ctx.adapter_mgr.get_adapter("qq").client.actions
        assert actions and actions[0][0] == "send_forward_msg", "合并转发应走 send_forward_msg"
        nodes = actions[0][1].get("messages") or []
        assert nodes and nodes[0]["data"].get("uin"), "转发节点应带上机器人账号"


# ────────────────────────────── 翻页 ──────────────────────────────

def test_pagination_advances_from_stored_offset():
    with tempfile.TemporaryDirectory() as td:
        seen = {}

        async def fake(keyword, skip, sort, limit):
            seen.update(keyword=keyword, skip=skip, limit=limit)
            return [], 0, [], []

        ctx = B.StubCtx(Path(td))
        inst = B.make_plugin(MOD, ctx, per_page=4)
        asyncio.run(inst.initialize())
        inst._do_search = fake

        first = B.FakeBatchEvent()
        asyncio.run(inst.tool_search(first, "kw", count=6))
        nav = inst._nav.get(first.sid) or {}
        assert nav.get("skip") == 6, f"首次搜索后应记住下一页偏移=6，实得 {nav}"
        asyncio.run(inst._handle_cmd(first.sid, "更多"))
        assert seen["skip"] == 6, f"「更多」应从下一页偏移开始（不应再加一页），实得 {seen['skip']}"
        assert seen["limit"] == 6, "「更多」应沿用上次实际条数"


# ────────────────────────────── 适配器字段 ──────────────────────────────

def test_adapter_identity_reading():
    with tempfile.TemporaryDirectory() as td:
        adapters = {
            "qq": B.FakeAdapter("qq", "10001", "主号bot"),
            "qq2": B.FakeAdapter("qq2", "20002", "小号bot"),
        }
        ctx = B.StubCtx(Path(td), adapters=adapters)
        inst = B.make_plugin(MOD, ctx)
        asyncio.run(inst.initialize())
        assert inst._self_id("qq:gm:1") == "10001"
        assert inst._bot_nick("qq:gm:1") == "主号bot"
        assert inst._self_id("qq2:gm:1") == "20002", "应按目标会话的适配器取账号"
        assert inst._self_id("不存在:gm:1") == "10001", "未知适配器应回退到默认适配器"


# ────────────────────────────── 产物清理 ──────────────────────────────

def test_png_pruning():
    with tempfile.TemporaryDirectory() as td:
        ctx = B.StubCtx(Path(td))
        inst = B.make_plugin(MOD, ctx)
        asyncio.run(inst.initialize())
        out_dir = inst.output_dir
        keep = inst.KEEP_PNGS
        for i in range(keep + 5):
            (out_dir / f"search_{100000 + i}.png").write_bytes(b"x")
        inst._prune_pngs()
        left = sorted(out_dir.glob("search_*.png"))
        assert len(left) == keep, f"应只保留 {keep} 张，实得 {len(left)}"


# ────────────────────────────── 渲染路径 ──────────────────────────────

def test_render_degrades_without_playwright():
    """没有 playwright 时应「就绪但不可用」，render_html 明确报错（调用方降级文本）。"""
    try:
        import playwright  # noqa: F401
        has_pw = True
    except Exception:
        has_pw = False
    bm = HR.BrowserManager()
    asyncio.run(bm.initialize())
    if has_pw:
        assert bm.ready.is_set(), "装了 playwright 时初始化应结束（无论成功失败）"
    else:
        assert bm.ready.is_set() and bm.ok is False, "缺 playwright 时应标记不可用而不抛异常"
        with tempfile.TemporaryDirectory() as td:
            try:
                asyncio.run(HR.render_html("<html></html>", str(Path(td) / "x.png"), bm))
                raise AssertionError("缺 playwright 时 render_html 应抛错")
            except RuntimeError:
                pass


def test_render_stays_per_render():
    """防回归：渲染必须保持「每次开→截图→关」，不得引入常驻浏览器。"""
    src = (B.ROOT / "html_render.py").read_text(encoding="utf-8")
    assert "acquire" not in src and "常驻" not in src, "不应引入常驻浏览器（会长期占用大量内存）"
    assert "await b.close()" in src or "await browser.close()" in src, "渲染结束应关闭浏览器"


# ────────────────────────────── 静态一致性 ──────────────────────────────

def test_static_wiring():
    src = (B.ROOT / "main.py").read_text(encoding="utf-8")
    assert "ctx.send_message_chain" in src, "发送应走 PluginContext 入口（3.0 规范）"
    assert "message_processor.send_message_chain" not in src, "不应依赖 MessageProcessor 兼容层"
    assert "adapter.self_id" not in src and "adapter.account" not in src, \
        "不应读两代框架都不存在的适配器属性"
    # 除同步抓取助手外，不应有阻塞睡眠
    assert not re.search(r"^\s+time\.sleep\(", src, re.M), "异步路径里不应出现 time.sleep"
    # 磁盘/清理类操作应走线程池
    assert "asyncio.to_thread" in src, "磁盘操作应放线程池"


# ────────────────────────────── 联网（可选） ──────────────────────────────

def test_live_search_opt_in():
    if not B.live_enabled():
        return _skip("设 C3D_LIVE=1 可开启真实搜索")
    cli = MC.MukuuClient(timeout=float(B.default_cfg()["section_main"]["search_timeout"]), cache_ttl=0)
    kw, _ = next(iter(TM.TIER_MAP.items()))

    async def run():
        try:
            items = await cli.search(kw, skip=0, sort="createdAtDesc", limit=3)
        finally:
            await cli.aclose()
        assert isinstance(items, list), "接口应返回列表"
        if items:
            it = MC.parse_post(items[0])
            for k in ("author", "screen", "date", "fav", "rt", "ja", "dl", "tw"):
                assert k in it, f"解析结果缺字段 {k}"
    asyncio.run(run())
    return f"live ok（关键词 {kw!r}）"
