# -*- coding: utf-8 -*-
"""
COM3D2 MOD 搜索插件（com3d2-mod-search）v1.0.0

- 直连 Mukuu JSON API（无外部网页提取依赖），httpx 单次请求秒回
- 三梯级关键词转换与自动下探内置在 tier_map.py，LLM 零消耗
- 双模式输出：HTML 渲染图（Playwright，参考 KiraAI_ai_html）或纯文本
- 合并转发卡片：渲染图/文本结果与链接清单打包成一条转发卡片发出（可配置）
- 入口：LLM 工具 search_com3d2_mods（默认开）+ 可自定义触发命令（默认关，两者独立配置）
"""
from __future__ import annotations

import asyncio
import base64
import html as html_mod
import json
import time
from pathlib import Path
from typing import List, Optional, Tuple

from core.plugin import BasePlugin, logger, on, Priority, register
from core.chat import MessageChain
from core.chat.message_elements import Text, Image
from core.chat.message_utils import KiraMessageEvent, KiraMessageBatchEvent

from .tier_map import build_queries
from .mukuu_client import MukuuClient, parse_post, serialize_items
from .html_render import BrowserManager, render_html

SORTS = ["createdAtDesc", "createdAtAsc", "retweetCountDesc", "favoriteCountDesc", "totalCountDesc"]
DEFAULT_COMMANDS = ["/com3d2"]

_BG_B64: Optional[str] = None


def _load_bg_b64() -> str:
    """加载 assets/bg.jpg 为 base64 data URI（用于渲染模板背景），失败返回空串。"""
    global _BG_B64
    if _BG_B64 is None:
        try:
            p = Path(__file__).parent / "assets" / "bg.jpg"
            _BG_B64 = base64.b64encode(p.read_bytes()).decode()
        except Exception as e:
            logger.warning(f"[com3d2-search] 背景图加载失败，使用纯色背景: {e}")
            _BG_B64 = ""
    return _BG_B64


def _esc(s) -> str:
    return html_mod.escape(str(s or ""), quote=False)


class Com3d2ModSearchPlugin(BasePlugin):
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        sec = cfg.get("section_main", {})
        self.enabled = bool(sec.get("enabled", True))
        self.enable_llm_tool = bool(sec.get("enable_llm_tool", True))
        self.enable_command = bool(sec.get("enable_command", False))
        self.send_as_forward = bool(sec.get("send_as_forward", True))
        raw_cmds = sec.get("commands", DEFAULT_COMMANDS)
        if isinstance(raw_cmds, list):
            self.commands = [str(c).strip() for c in raw_cmds if str(c).strip()]
        else:
            self.commands = [c.strip() for c in str(raw_cmds).splitlines() if c.strip()]
        if not self.commands:
            self.commands = list(DEFAULT_COMMANDS)
        self.mode = str(sec.get("mode", "image"))
        self.translate = bool(sec.get("translate", True))
        self.per_page = int(sec.get("per_page", 10))
        self.cache_ttl = int(sec.get("cache_ttl", 60))
        self.timeout = float(sec.get("search_timeout", 20))
        self.output_dir: Optional[Path] = None
        self._client: Optional[MukuuClient] = None
        self._browser = BrowserManager()
        # 翻页状态：sid -> {"word": str, "skip": int, "sort": str}
        self._nav: dict = {}

    # ==================== 生命周期 ====================

    async def initialize(self):
        self.output_dir = self.ctx.get_plugin_data_dir() / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._client = MukuuClient(timeout=self.timeout, cache_ttl=self.cache_ttl)
        # 浏览器后台检测，不阻塞加载
        asyncio.ensure_future(self._browser.initialize())
        logger.info(
            f"[com3d2-search] COM3D2 MOD 搜索插件加载完成 v1.0.0 "
            f"(llm_tool={self.enable_llm_tool} cmd={self.enable_command} cmds={self.commands} "
            f"forward={self.send_as_forward})"
        )

    async def terminate(self):
        # BrowserManager 无持久连接；MukuuClient 每次请求独立 client，无需关闭
        pass

    # ==================== LLM 工具 ====================

    @register.tool(
        name="search_com3d2_mods",
        description=(
            "搜索 COM3D2/CM3D2 MOD（数据源 Mukuu）。输入中文关键词即可，插件会自动转换为"
            "日文片假名/汉字/英文搜索并自动下探合并结果。根据配置会直接发送渲染图或文本结果到会话。"
            "工具返回结构化 JSON：每条含作者(author)、推特名(screen)、日期(date)、收藏(fav)、"
            "转发(rt)、日文原文(ja)、下载链接(dl)、推文链接(tw)。你需要把每条 ja 用中文翻译"
            "并展示给用户。翻页：再次用相同 keyword+sort 调用本工具即自动翻下一页；"
            "换 keyword 则重新开始。count 参数可覆盖本次返回条数（默认跟随配置）。"
        ),
        params={
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词，中文/日文/英文均可，如 口枷、ロングブーツ、gloves",
                },
                "sort": {
                    "type": "string",
                    "description": "排序方式",
                    "options": SORTS,
                    "default": "createdAtDesc",
                },
                "mode": {
                    "type": "string",
                    "description": "输出模式覆盖：空=跟随配置，image=渲染图+链接清单，text=纯文本，both=渲染图+完整文本",
                    "options": ["", "image", "text", "both"],
                    "default": "",
                },
                "count": {
                    "type": "integer",
                    "description": "本次返回条数（1~50），默认 0=跟随插件配置（每页条数）。bot 想一次要更多可传 20 等",
                    "default": 0,
                },
            },
            "required": ["keyword"],
        },
    )
    async def tool_search(self, event: KiraMessageBatchEvent, keyword: str, sort: str = "createdAtDesc", mode: str = "", count: int = 0) -> str:
        if not self.enabled:
            return "COM3D2 MOD 搜索插件未启用"
        if not self.enable_llm_tool:
            return "COM3D2 MOD 搜索的 LLM 工具已关闭（可在插件配置中开启）"
        sid = event.sid
        effective = mode if mode in ("image", "text", "both") else self.mode
        limit = count if count and count > 0 else self.per_page
        if limit > 50:
            limit = 50
        # 翻页：相同关键词+排序再次调用 → 自动翻下一页；不同关键词 → 重新开始
        nav = self._nav.get(sid, {})
        if nav.get("word") == keyword and nav.get("sort") == sort:
            skip = nav.get("skip", 0)
        else:
            skip = 0
        try:
            result = await self._search_and_show(
                sid, keyword, sort=sort, mode=effective, update_nav=True,
                force_skip=skip, self_id=self._event_self_id(event), limit=limit,
            )
            return result
        except Exception as e:
            logger.exception("[com3d2-search] 工具调用失败")
            return f"COM3D2 MOD 搜索失败：{e}"

    # ==================== 命令 ====================

    @on.im_message(priority=Priority.HIGH)
    async def on_cmd(self, event: KiraMessageEvent, *_):
        if not self.enabled or not self.enable_command:
            return
        text = "".join(m.text for m in event.message.chain if isinstance(m, Text)).strip()
        cmd = self._match_command(text)
        if cmd is None:
            return
        sid = event.session.sid
        arg = text[len(cmd):].strip()
        try:
            await self._handle_cmd(sid, arg, self_id=self._event_self_id(event))
        except Exception:
            logger.exception("[com3d2-search] 命令处理失败")
        # 命令已处理，阻止进入 LLM 流程
        event.discard()

    def _match_command(self, text: str) -> Optional[str]:
        """匹配最长命令前缀；text 为空或未命中返回 None。"""
        if not text:
            return None
        hit = None
        for c in self.commands:
            if text.startswith(c) and (hit is None or len(c) > len(hit)):
                hit = c
        return hit

    def _event_self_id(self, event) -> str:
        return str(getattr(event, "self_id", "") or "")

    def _help_text(self) -> str:
        cmd = self.commands[0] if self.commands else "/com3d2"
        return (
            "COM3D2 MOD 搜索（Mukuu）\n"
            f"{cmd} 口枷 → 搜索（渲染图+链接清单）\n"
            f"{cmd} 文本 口枷 → 纯文本输出\n"
            f"{cmd} 图 口枷 → 强制渲染图\n"
            f"{cmd} 更多 → 翻下一页\n"
            f"{cmd} 重置 → 重置翻页\n"
            "也可以直接让我搜索，我会翻译每条描述"
        )

    async def _handle_cmd(self, sid: str, arg: str, self_id: str = ""):
        if not arg:
            await self._send(sid, MessageChain([Text(self._help_text())]))
            return
        low = arg.lower()
        if low in ("更多", "下一页", "翻页", "next"):
            nav = self._nav.get(sid)
            if not nav:
                await self._send(sid, MessageChain([Text("还没有搜索记录，先搜索关键词吧")]))
                return
            skip = nav["skip"] + self.per_page
            await self._search_and_show(
                sid, nav["word"], sort=nav.get("sort", "createdAtDesc"),
                mode=self.mode, update_nav=True, force_skip=skip,
                self_id=self_id,
            )
            return
        if low in ("重置", "reset", "清空"):
            self._nav.pop(sid, None)
            await self._send(sid, MessageChain([Text("已重置翻页状态")]))
            return
        mode = self.mode
        kw = arg
        if arg.startswith("图 "):
            mode, kw = "image", arg[2:].strip()
        elif arg.startswith("文本 "):
            mode, kw = "text", arg[3:].strip()
        if not kw:
            await self._send(sid, MessageChain([Text(self._help_text())]))
            return
        await self._search_and_show(sid, kw, sort="createdAtDesc", mode=mode, update_nav=True, self_id=self_id)

    # ==================== 核心搜索 ====================

    async def _do_search(
        self, keyword: str, skip: int, sort: str, limit: int
    ) -> Tuple[List[dict], int, List[Tuple[str, str, int]], List[Tuple[str, str]]]:
        """三梯级搜索：片假名→汉字→英文，≤3 件或 0 件自动下探合并。

        Mukuu 为 Heroku 免费实例，冷启动可能 5~10s，单梯级失败重试一次。
        """
        queries = build_queries(keyword)
        if not queries:
            return [], 0, [], []
        items: List[dict] = []
        used: List[Tuple[str, str, int]] = []
        total = 0
        for q, tier in queries:
            page, cnt = [], 0
            for attempt in range(2):
                try:
                    page = await self._client.search(q, skip=skip, sort=sort, limit=limit)
                    cnt = await self._client.count(q, sort=sort)
                    break
                except Exception as e:
                    logger.warning(f"[com3d2-search] 梯级查询失败 {q} (try {attempt + 1}): {e}")
                    if attempt == 0:
                        await asyncio.sleep(0.5)
            if not page and not cnt:
                used.append((q, tier, -1))
                continue
            used.append((q, tier, cnt))
            total = max(total, cnt)
            for p in page:
                it = parse_post(p)
                if it["tw"] and any(x["tw"] == it["tw"] for x in items):
                    continue
                items.append(it)
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break
        return items, total, used, queries

    async def _search_and_show(
        self, sid: str, keyword: str, sort: str = "createdAtDesc", mode: str = "image",
        update_nav: bool = False, force_skip: Optional[int] = None, self_id: str = "",
        limit: Optional[int] = None,
    ) -> str:
        limit = limit or self.per_page
        skip = force_skip if force_skip is not None else (self._nav.get(sid, {}).get("skip", 0) if not update_nav else 0)
        items, total, used, queries = await self._do_search(keyword, skip, sort, limit)
        if update_nav:
            self._nav[sid] = {"word": keyword, "skip": skip + limit, "sort": sort}

        if not items:
            note = "未找到结果" if not used else f"未找到结果（尝试：{'、'.join(q for q, _, _ in used)}）"
            await self._send(sid, MessageChain([Text(f"🔍「{keyword}」{note}")]))
            return json.dumps({"keyword": keyword, "total": 0, "items": [], "note": note}, ensure_ascii=False)

        sent_desc = await self._send_results(sid, mode, keyword, total, sort, items, self_id=self_id)
        return json.dumps(self._tool_payload(keyword, used, total, items, sent_desc), ensure_ascii=False)

    def _tool_payload(self, keyword, used, total, items, sent_desc) -> dict:
        payload = {
            "keyword": keyword,
            "used": [[q, tier, cnt] for q, tier, cnt in used],
            "total": total,
            "sent": sent_desc,
            "items": json.loads(serialize_items(items)),
        }
        if self.translate:
            payload["note"] = "请把每条 ja（日文原文）用一行中文翻译展示给用户，保持编号一致"
        else:
            payload["note"] = "翻译已关闭，直接展示原文与链接即可"
        return payload

    # ==================== 展示构建 ====================

    def _format_text(self, keyword: str, total: int, items: List[dict]) -> str:
        lines = [f"🔍「{keyword}」{total}件"]
        for i, it in enumerate(items, 1):
            lines.append(
                f"① {it['author']} @{it['screen']} | {it['date']} | ❤{it['fav']}🔄{it['rt']}"
            )
            lines.append(f"　{it['ja']}")
            for dl in it["dl"]:
                lines.append(f"　📥 {dl}")
            if it["tw"]:
                lines.append(f"　🔗 {it['tw']}")
            lines.append("")
        return "\n".join(lines).strip()

    def _build_link_list(self, items: List[dict]) -> str:
        lines = ["🔗 链接清单（①=第1条，可长按复制）"]
        for i, it in enumerate(items, 1):
            for dl in it["dl"]:
                lines.append(f"{i} 📥 {dl}")
            if it["tw"]:
                lines.append(f"{i} 🔗 {it['tw']}")
        return "\n".join(lines)

    def _build_html(self, keyword: str, total: int, sort: str, items: List[dict]) -> str:
        cards = []
        for i, it in enumerate(items, 1):
            links = []
            for dl in it["dl"]:
                links.append(f'<div class="link dl">📥 <span class="u">{_esc(dl)}</span></div>')
            if it["tw"]:
                links.append(f'<div class="link tw">🔗 <span class="u">{_esc(it["tw"])}</span></div>')
            cards.append(
                '<div class="post">'
                f'<div class="head"><span class="idx">#{i}</span> '
                f'<span class="author">{_esc(it["author"])}</span> '
                f'<span class="screen">@{_esc(it["screen"])}</span> '
                f'<span class="date">{_esc(it["date"])}</span> '
                f'<span class="stats">❤{it["fav"]} 🔄{it["rt"]}</span></div>'
                f'<div class="body">{_esc(it["ja"])}</div>'
                f'{"".join(links)}'
                "</div>"
            )
        bg = _load_bg_b64()
        bg_layer = ""
        bg_style = ""
        if bg:
            bg_layer = '<div class="bg"></div>'
            bg_style = (
                ".bg{position:absolute;top:0;left:0;right:0;bottom:0;z-index:-1;"
                "background:"
                "linear-gradient(180deg, rgba(12,13,18,0.3) 0%, rgba(12,13,18,0.2) 16%, rgba(12,13,18,0.5) 24%, rgba(12,13,18,0.75) 34%, rgba(12,13,18,0.6) 70%, rgba(18,20,27,0.96) 100%),"
                f"url('data:image/jpeg;base64,{bg}') calc(50% + 40px) calc(50% - 10px) / cover no-repeat;}}"
            )
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html{{height:100%;}}
body{{margin:0;width:800px;min-height:100%;box-sizing:border-box;position:relative;background:#14161c;color:#e8eaf0;
font-family:"PingFang SC","Microsoft YaHei",-apple-system,sans-serif;font-size:14px;}}
{bg_style}
.wrap{{padding:0 24px 16px;}}
.header{{padding-top:385px;margin-bottom:16px;}}
.header .title{{font-size:19px;font-weight:700;color:#ffd28a;}}
.header .meta{{margin-top:6px;font-size:12px;color:#aab2c5;}}
.post{{background:rgba(30,34,45,0.86);border:1px solid rgba(44,50,66,0.9);border-radius:12px;padding:12px 14px;margin-bottom:12px;}}
.head{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px;}}
.idx{{color:#ffd28a;font-weight:700;}}
.author{{font-weight:600;color:#fff;}}
.screen{{color:#7aa2ff;font-size:12px;}}
.date{{color:#aab2c5;font-size:12px;}}
.stats{{color:#ff9e9e;font-size:12px;margin-left:auto;}}
.body{{white-space:pre-wrap;word-break:break-all;line-height:1.55;color:#d6dae6;}}
.link{{margin-top:6px;font-size:12.5px;word-break:break-all;}}
.link.dl{{color:#9be89b;}}
.link.tw{{color:#7aa2ff;}}
.link .u{{color:inherit;}}
.footer{{margin-top:14px;padding:10px 0 4px;text-align:center;font-size:12px;color:#8f97ab;line-height:1.7;}}
</style></head><body>
{bg_layer}
<div class="wrap">
<div class="header">
  <div class="title">🔍「{_esc(keyword)}」{total}件</div>
  <div class="meta">排序 {_esc(sort)} · 数据源 Mukuu · 共{len(items)}条展示</div>
</div>
{''.join(cards)}
<div class="footer">provide by @znq19</div>
</div>
</body></html>"""
        return html

    # ==================== 发送 ====================

    async def _send_results(
        self, sid: str, mode: str, keyword: str, total: int, sort: str,
        items: List[dict], self_id: str = "",
    ) -> str:
        """按模式产出并发送结果（合并转发 or 直发），返回发送描述。"""
        png: Optional[Path] = None
        if mode in ("image", "both"):
            try:
                png = await self._render_png(keyword, total, sort, items)
            except Exception as e:
                logger.warning(f"[com3d2-search] 渲染失败，降级文本: {e}")
                mode = "text"

        if self.send_as_forward:
            nodes = []
            if png:
                nodes.append(self._node_image(png))
            nodes.append(self._node_text(
                self._build_link_list(items) if mode == "image" else self._format_text(keyword, total, items)
            ))
            try:
                await self._send_forward(sid, nodes, self_id=self_id)
                if png:
                    return "渲染图+链接清单已发送（合并转发）" if mode == "image" else "渲染图+完整文本已发送（合并转发）"
                return "文本结果已发送（合并转发）"
            except Exception as e:
                logger.warning(f"[com3d2-search] 合并转发失败，降级直发: {e}")
                # 继续走直发

        # 直发
        if png:
            await self._send(sid, MessageChain([Image(image=str(png))]))
        if mode == "image":
            await self._send(sid, MessageChain([Text(self._build_link_list(items))]))
            return "渲染图已发送 + 链接清单已发送" if png else "渲染失败已降级文本"
        await self._send(sid, MessageChain([Text(self._format_text(keyword, total, items))]))
        return "渲染图+完整文本已发送" if png else "渲染失败已降级文本"

    async def _render_png(self, keyword: str, total: int, sort: str, items: List[dict]) -> Path:
        html = self._build_html(keyword, total, sort, items)
        ts = int(time.time() * 1000)
        png = self.output_dir / f"search_{ts}.png"
        await render_html(html, str(png), self._browser)
        return png

    # ---- 合并转发 ----

    def _node_image(self, path: Path) -> dict:
        return {
            "type": "node",
            "data": {
                "name": self._bot_nick(),
                "uin": self._self_id(),
                "content": [{"type": "image", "data": {"file": str(Path(path).resolve())}}],
            },
        }

    def _node_text(self, text: str) -> dict:
        return {
            "type": "node",
            "data": {
                "name": self._bot_nick(),
                "uin": self._self_id(),
                "content": [{"type": "text", "data": {"text": text}}],
            },
        }

    def _bot_nick(self) -> str:
        try:
            adapter = self.ctx.adapter_mgr.get_adapter("qq")
            return getattr(getattr(adapter, "info", None), "name", None) or "COM3D2搜索"
        except Exception:
            return "COM3D2搜索"

    def _self_id(self) -> str:
        try:
            adapter = self.ctx.adapter_mgr.get_adapter("qq")
            return str(getattr(adapter, "self_id", "") or getattr(adapter, "account", "") or "")
        except Exception:
            return ""

    async def _send_forward(self, sid: str, nodes: List[dict], self_id: str = ""):
        """通过适配器发送合并转发卡片（OneBot send_forward_msg）。"""
        parts = sid.split(":")
        if len(parts) != 3:
            raise ValueError(f"无效 session_id: {sid}")
        adapter_name, session_type, target_id = parts

        adapter_inst = self.ctx.adapter_mgr.get_adapter(adapter_name)
        if not adapter_inst:
            raise ValueError(f"无法获取适配器: {adapter_name}")
        client = adapter_inst.get_client()
        if not client:
            raise ValueError("无法获取客户端")

        for node in nodes:
            if not node["data"].get("uin"):
                node["data"]["uin"] = self_id or self._self_id()

        if session_type == "gm":
            await client.send_action("send_forward_msg", {
                "group_id": int(target_id),
                "messages": nodes,
            })
        else:
            await client.send_action("send_forward_msg", {
                "user_id": int(target_id),
                "messages": nodes,
            })

    async def _send(self, sid: str, chain: MessageChain):
        await self.ctx.message_processor.send_message_chain(sid, chain)
