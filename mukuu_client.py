# -*- coding: utf-8 -*-
"""
Mukuu JSON API 客户端：直连 https://mukuu.herokuapp.com/api/v1

- 不依赖任何外部网页提取服务，httpx 直连
- 内置结果缓存（同关键词+翻页+排序，TTL 可配）
- 单次请求超时可控
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

API_BASE = "https://mukuu.herokuapp.com/api/v1"

# 下载链接只认这些域名（与 Mukuu 前端一致）
ACCEPTED_DOMAINS = ("getuploader.com", "drive.google.com", "mega.nz", "github.com")

_URL_RE = re.compile(r"https?://[^\s<>\"'）)】]+")


def extract_download_links(text: str) -> List[str]:
    """从推文正文提取 MOD 下载链接（限定 Mukuu 收录域名）。"""
    if not text:
        return []
    out = []
    for u in _URL_RE.findall(text):
        u = u.rstrip(".,;:")
        if any(d in u for d in ACCEPTED_DOMAINS) and u not in out:
            out.append(u)
    return out


class MukuuClient:
    """Mukuu 搜索 API 客户端（线程安全：每次请求独立）。"""

    def __init__(self, timeout: float = 10.0, cache_ttl: int = 300):
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        # 缓存键含 limit：否则先 count=20 再 count=5 会拿到 20 条（旧实现漏了 limit）
        self._cache: Dict[Tuple[str, int, str, int], Tuple[float, Any]] = {}
        self._client: Optional[httpx.AsyncClient] = None      # 常驻客户端（连接复用）

    async def aclose(self):
        """关闭常驻客户端（插件 terminate 时调用；可重入）。"""
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass

    # ---------- 公开方法 ----------

    async def search(
        self,
        word: str,
        skip: int = 0,
        sort: str = "createdAtDesc",
        higher_retweet: int = 0,
        limit: int = 5,
    ) -> List[dict]:
        """搜索并返回解析后的帖子列表（原始 dict）。"""
        key = (word, skip, sort, limit)
        cached = self._get_cache(key)
        if cached is not None:
            return cached
        payload = {
            "data": {
                "limit": limit,
                "skip": skip,
                "searchWord": word,
                "sort": sort,
                "higherRetweet": higher_retweet,
            }
        }
        data = await self._post("/posts/list", payload)
        items = data if isinstance(data, list) else []
        self._set_cache(key, items)
        return items

    async def count(
        self, word: str, sort: str = "createdAtDesc", higher_retweet: int = 0
    ) -> int:
        """获取搜索结果总数。"""
        payload = {
            "data": {
                "searchWord": word,
                "sort": sort,
                "higherRetweet": higher_retweet,
            }
        }
        data = await self._post("/posts/count", payload)
        if isinstance(data, dict):
            return int(data.get("count", 0) or 0)
        return 0

    # ---------- 内部 ----------

    def _ensure_client(self) -> httpx.AsyncClient:
        """常驻客户端：复用连接（省 TLS 握手），超时随配置；失效时自动重建。"""
        client = self._client
        if client is None or getattr(client, "is_closed", False):
            client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"Accept": "application/json",
                         "User-Agent": "KiraAI-com3d2-search/0.1"},
            )
            self._client = client
        return client

    async def _post(self, path: str, payload: dict) -> Any:
        client = self._ensure_client()
        try:
            resp = await client.post(API_BASE + path, json=payload)
        except Exception:
            # 连接池坏了（对端断开等）⇒ 重建一次再试，仍失败则上抛
            try:
                await client.aclose()
            except Exception:
                pass
            self._client = None
            client = self._ensure_client()
            resp = await client.post(API_BASE + path, json=payload)
        resp.raise_for_status()
        return resp.json()

    def _get_cache(self, key: Tuple[str, int, str, int]):
        if self.cache_ttl <= 0:
            return None
        hit = self._cache.get(key)
        if not hit:
            return None
        ts, val = hit
        if time.time() - ts > self.cache_ttl:
            self._cache.pop(key, None)
            return None
        return val

    def _set_cache(self, key: Tuple[str, int, str, int], val):
        if self.cache_ttl <= 0:
            return
        # 简单防膨胀：超过 64 条清空
        if len(self._cache) >= 64:
            self._cache.clear()
        self._cache[key] = (time.time(), val)

    def clear_cache(self):
        self._cache.clear()


def parse_post(post: dict) -> dict:
    """原始帖子 → 精简结构化条目（供 LLM 与渲染使用）。"""
    posted_by = post.get("postedBy") or {}
    screen = posted_by.get("screenName") or ""
    id_str = str(post.get("idStr") or "")
    text = post.get("text") or ""
    return {
        "author": posted_by.get("name") or "",
        "screen": screen,
        "date": str(post.get("createdAt") or "")[:10],
        "fav": int(post.get("favoriteCount") or 0),
        "rt": int(post.get("retweetCount") or 0),
        "ja": text,
        "dl": extract_download_links(text),
        "tw": f"https://twitter.com/{screen}/status/{id_str}" if screen and id_str else "",
    }


def serialize_items(items: List[dict]) -> str:
    """条目列表 → 紧凑 JSON 字符串（给 LLM 的返回）。"""
    out = []
    for i, it in enumerate(items, 1):
        out.append(
            {
                "n": i,
                "author": it["author"],
                "screen": it["screen"],
                "date": it["date"],
                "fav": it["fav"],
                "rt": it["rt"],
                "ja": it["ja"],
                "dl": it["dl"],
                "tw": it["tw"],
            }
        )
    return json.dumps(out, ensure_ascii=False)
