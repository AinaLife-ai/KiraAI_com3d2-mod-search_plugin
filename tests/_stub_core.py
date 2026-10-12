# -*- coding: utf-8 -*-
"""最小框架桩：仅在**没有**真 KiraAI core 可用时安装（让插件能被导入并跑起来）。

只实现插件实际用到的表层 API：BasePlugin / logger / on / Priority / register /
MessageChain / Text / Image / 事件类型。行为刻意保持"惰性"——装饰器不注册、只返回原函数，
因为测试关注的是插件自身的逻辑，而不是框架的调度。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, List, Optional


class _Logger:
    def __init__(self, name: str = "plugin"):
        self.name = name

    def _log(self, level: str, msg: str, *a: Any, **k: Any):
        try:
            text = msg % a if a else msg
        except Exception:
            text = f"{msg} {a}"
        # 默认安静；需要看日志时设 C3D_TEST_VERBOSE=1
        import os
        if os.environ.get("C3D_TEST_VERBOSE"):
            print(f"[{level}] {text}")

    def info(self, msg, *a, **k): self._log("info", msg, *a, **k)
    def warning(self, msg, *a, **k): self._log("warn", msg, *a, **k)
    def error(self, msg, *a, **k): self._log("error", msg, *a, **k)
    def exception(self, msg, *a, **k): self._log("error", msg, *a, **k)
    def debug(self, msg, *a, **k): self._log("debug", msg, *a, **k)

    def setLevel(self, *a, **k):  # noqa: N802 (兼容 logging API)
        return None


logger = _Logger()


class Priority:
    SYS_LOW = -100
    LOW = -50
    MEDIUM = 0
    HIGH = 50
    SYS_HIGH = 100


class BasePlugin:
    def __init__(self, ctx: Any, cfg: dict):
        self.ctx = ctx
        self.plugin_cfg = cfg

    async def initialize(self):
        pass

    async def terminate(self):
        pass


class _LazyDecorators:
    """`on.<event>(...)` / `register.<kind>(...)`：不注册，只把原函数返回。"""

    def __getattr__(self, _name: str):
        def factory(*args: Any, **kwargs: Any):
            def deco(func):
                return func
            return deco
        return factory


on = _LazyDecorators()
register = _LazyDecorators()


class Text:
    def __init__(self, text: str = ""):
        self.text = text
        self.repr = text

    def __repr__(self):
        return f"Text({self.text!r})"


class Image:
    def __init__(self, image: str = "", **kwargs: Any):
        self.image = image
        self.repr = "<image>"

    def __repr__(self):
        return f"Image({self.image!r})"


class MessageChain:
    def __init__(self, elements: Optional[List[Any]] = None):
        self.message_list: List[Any] = list(elements or [])

    def text(self, t: str):
        self.message_list.append(Text(t)); return self

    def image(self, i: str):
        self.message_list.append(Image(i)); return self

    def __iter__(self):
        return iter(self.message_list)

    def __len__(self):
        return len(self.message_list)


class KiraMessageEvent:
    """测试里一般用自定义的假事件；此桩仅为导入与类型判断服务。"""

    def __init__(self, adapter=None, message=None, timestamp: int = 0,
                 supported_elements=None, message_types=None, **kwargs: Any):
        self.adapter = adapter
        self.message = message
        self.timestamp = timestamp
        self.supported_elements = supported_elements or message_types or []


class KiraMessageBatchEvent(KiraMessageEvent):
    @property
    def sid(self) -> str:
        sess = getattr(self, "session", None)
        return getattr(sess, "sid", "") if sess else ""

    @property
    def self_id(self) -> str:
        return str(getattr(self, "self_id_", "") or "")


def _ensure_pkg(name: str, path: Optional[str] = None) -> types.ModuleType:
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        if path:
            mod.__path__ = [path]
        sys.modules[name] = mod
    return mod


def install() -> bool:
    """安装最小 core 桩。返回是否真的装了（已存在真 core 时返回 False）。"""
    try:
        import core.plugin  # noqa: F401  真框架在 ⇒ 什么都不做
        return False
    except Exception:
        pass

    core = _ensure_pkg("core")
    chat = _ensure_pkg("core.chat")
    utils = _ensure_pkg("core.utils")

    plugin = _ensure_pkg("core.plugin")
    plugin.BasePlugin = BasePlugin
    plugin.logger = logger
    plugin.on = on
    plugin.register = register
    plugin.Priority = Priority

    chat.MessageChain = MessageChain
    chat.Text = Text
    chat.Image = Image

    me = _ensure_pkg("core.chat.message_elements")
    me.Text = Text
    me.Image = Image

    mu = _ensure_pkg("core.chat.message_utils")
    mu.KiraMessageEvent = KiraMessageEvent
    mu.KiraMessageBatchEvent = KiraMessageBatchEvent

    pu = _ensure_pkg("core.utils.path_utils")

    def get_config_path() -> Path:
        p = Path.cwd() / "data" / "config"
        p.mkdir(parents=True, exist_ok=True)
        return p

    pu.get_config_path = get_config_path
    pu.get_data_path = lambda: Path.cwd() / "data"
    return True


def install_fake_httpx() -> bool:
    """没装 httpx 时给一个够用的假实现（只为让插件模块可导入、可测逻辑）。"""
    try:
        import httpx  # noqa: F401
        return False
    except Exception:
        pass

    mod = types.ModuleType("httpx")

    class Response:
        def __init__(self, data: Any = None, status: int = 200):
            self._data = data if data is not None else []
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._data

    class AsyncClient:
        def __init__(self, *a: Any, **k: Any):
            self.is_closed = False
            self.posts = 0

        async def post(self, url: str, json: Any = None, **kw: Any):
            self.posts += 1
            return Response([])

        async def aclose(self):
            self.is_closed = True

    mod.AsyncClient = AsyncClient
    mod.Response = Response
    mod.__version__ = "0.0.0-stub"
    sys.modules["httpx"] = mod
    return True
