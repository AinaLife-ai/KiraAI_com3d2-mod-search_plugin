# -*- coding: utf-8 -*-
"""测试引导：定位插件根目录、准备运行环境、把插件当包加载、提供可复用的测试替身。

设计取向（避免任何硬编码与外部依赖）：
- **不写死路径**：插件根由 `__file__` 反推（本文件在 <plugin_root>/tests/ 下）；
- **不写死版本/数据**：需要版本就读 manifest.json，需要关键词就从 TIER_MAP 里取；
- **不依赖第三方**：没有 httpx 就注入最小假实现；没有 playwright 就跳过渲染相关断言；
- **不依赖框架**：有真 KiraAI core（可用 KIRA_CORE 指向它）就用真的，否则装最小桩；
- **不依赖网络**：默认只跑离线用例，联网用例需显式 `C3D_LIVE=1`。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from typing import Any, List, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # 插件根（main.py 所在处）
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import _stub_core  # noqa: E402

USING_STUB = _stub_core.install()
FAKE_HTTPX = _stub_core.install_fake_httpx()

# 真框架优先：KIRA_CORE 指向 KiraAI 的 core 目录（其父目录用作 sys.path）
_core_env = os.environ.get("KIRA_CORE") or os.environ.get("KIRA_CORE_DIR")
if _core_env and Path(_core_env).is_dir():
    parent = str(Path(_core_env).resolve().parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    USING_STUB = _stub_core.install()

PKG_NAME = "com3d2_mod_search"


def load_plugin() -> types.ModuleType:
    """把插件按包加载（支持 `from .tier_map import ...` 这类相对导入）。"""
    if PKG_NAME in sys.modules:
        return sys.modules[PKG_NAME]
    pkg = types.ModuleType(PKG_NAME)
    pkg.__path__ = [str(ROOT)]
    pkg.__package__ = PKG_NAME
    sys.modules[PKG_NAME] = pkg
    spec = importlib.util.spec_from_file_location(f"{PKG_NAME}.main", str(ROOT / "main.py"))
    assert spec and spec.loader, "无法定位 main.py"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"{PKG_NAME}.main"] = mod
    spec.loader.exec_module(mod)
    return mod


def manifest() -> dict:
    return json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def schema() -> dict:
    return json.loads((ROOT / "schema.json").read_text(encoding="utf-8"))


def live_enabled() -> bool:
    return str(os.environ.get("C3D_LIVE", "")).strip() in ("1", "true", "yes", "on")


# --------------------------------------------------------------------------
# 测试替身
# --------------------------------------------------------------------------

class RecordingSender:
    """记录 ctx.send_message_chain 的调用（插件所有直发都经过它）。"""

    def __init__(self):
        self.sent: List[Tuple[str, str]] = []

    async def send_message_chain(self, sid: str, chain, **kwargs):
        parts = []
        for el in getattr(chain, "message_list", []):
            parts.append(getattr(el, "text", None) or f"<{type(el).__name__}>")
        self.sent.append((sid, " | ".join(parts)))
        return None

    def texts(self) -> List[str]:
        return [t for _, t in self.sent]


class RecordingAdapterClient:
    def __init__(self):
        self.actions: List[Tuple[str, dict]] = []

    async def send_action(self, action: str, payload: dict):
        self.actions.append((action, payload))
        return {"status": "ok"}


class FakeAdapter:
    def __init__(self, name: str = "qq", self_id: str = "", nickname: str = ""):
        self.info = types.SimpleNamespace(name=name, platform="QQ")
        self.config = {"self_id": self_id, "nickname": nickname}
        self.client = RecordingAdapterClient()

    def get_client(self):
        return self.client


class FakeAdapterMgr:
    def __init__(self, adapters: dict):
        self._adapters = adapters

    def get_adapter(self, name: str):
        return self._adapters.get(name)


class StubCtx:
    """够用的 ctx：数据目录 + 发送记录 + 适配器表（按需注入）。"""

    def __init__(self, data_dir: Path, adapters: dict | None = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sender = RecordingSender()
        self.adapter_mgr = FakeAdapterMgr(adapters or
                                          {"qq": FakeAdapter("qq", "10001", "测试bot")})
        self.message_processor = self.sender     # 兼容旧入口（插件已改走 ctx）

    # —— 插件实际调用的接口 ——
    def get_plugin_data_dir(self) -> Path:
        return self.data_dir

    async def send_message_chain(self, sid: str, chain, **kwargs):
        return await self.sender.send_message_chain(sid, chain, **kwargs)

    def get_llm_client(self, *a, **k):
        return None

    def get_default_llm_client(self):
        return None


class FakeBatchEvent:
    """工具入口的 KiraMessageBatchEvent 替身（只需 sid / self_id）。"""

    def __init__(self, sid: str = "qq:gm:100", self_id: str = "10001"):
        self.sid = sid
        self.self_id = self_id


def default_cfg(**overrides: Any) -> dict:
    """默认配置（字段名与 schema.json 保持一致；不写死任何"业务常量"）。"""
    sec = {
        "enabled": True,
        "enable_llm_tool": True,
        "enable_command": True,
        "commands": ["/com3d2"],
        "send_as_forward": True,
        "mode": "text",             # 测试统一用文本模式：无需 playwright
        "translate": True,
        "per_page": 3,
        "cache_ttl": 60,
        "search_timeout": 10,
        "notify_empty": False,
    }
    sec.update(overrides)
    return {"section_main": sec}


def make_plugin(mod: types.ModuleType, ctx: StubCtx, **cfg_overrides: Any):
    return mod.Com3d2ModSearchPlugin(ctx, default_cfg(**cfg_overrides))


def synthetic_items(n: int = 2) -> List[dict]:
    """合成条目（字段与 mukuu_client.parse_post 的输出保持一致）。"""
    out = []
    for i in range(1, n + 1):
        out.append({
            "author": f"作者{i}", "screen": f"user{i}", "date": f"2026-01-0{i}",
            "fav": i * 10, "rt": i, "ja": f"テスト{i}",
            "dl": [f"https://mega.nz/file/{i}"],
            "tw": f"https://twitter.com/user{i}/status/{i}",
        })
    return out
