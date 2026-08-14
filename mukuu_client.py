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
        self._cache: Dict[Tuple[str, int, str], Tuple[float, Any]] = {}

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
        key = (word, skip, sort)
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

    async def _post(self, path: str, payload: dict) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                API_BASE + path,
                json=payload,
                headers={"Accept": "application/json", "User-Agent": "KiraAI-com3d2-search/0.1"},
            )
            resp.raise_for_status()
            return resp.json()

    def _get_cache(self, key: Tuple[str, int, str]):
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

    def _set_cache(self, key: Tuple[str, int, str], val):
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
