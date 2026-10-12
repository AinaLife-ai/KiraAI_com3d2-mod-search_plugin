#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线测试运行器：不依赖 pytest / playwright / 网络。

    python tests/run_tests.py            # 跑全部离线用例
    C3D_LIVE=1 python tests/run_tests.py # 额外跑一次真实 Mukuu 搜索
    KIRA_CORE=/path/to/kira/core python tests/run_tests.py   # 用真框架而不是内置桩

退出码 0 = 全部通过。
"""
from __future__ import annotations

import asyncio
import inspect
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import test_plugin as T  # noqa: E402


def main() -> int:
    passed, failed, skipped = 0, 0, 0
    names = [n for n in dir(T) if n.startswith("test_") and callable(getattr(T, n))]
    names.sort()
    print(f"com3d2-mod-search 测试 · 共 {len(names)} 项"
          f"（框架={'真 KiraAI core' if not T.B.USING_STUB else '内置最小桩'}、"
          f"httpx={'真包' if not T.B.FAKE_HTTPX else '内置假实现'}、"
          f"联网={'开' if T.B.live_enabled() else '关'}）\n")
    for name in names:
        fn = getattr(T, name)
        try:
            result = fn()
            if inspect.iscoroutine(result):
                result = asyncio.run(result)
            if isinstance(result, str) and result.startswith("skipped"):
                skipped += 1
                print(f"  ○ {name} — {result}")
            else:
                passed += 1
                extra = f" — {result}" if result else ""
                print(f"  ✓ {name}{extra}")
        except BaseException as e:                     # pytest 的 Skipped 继承自 BaseException
            if type(e).__name__ == "Skipped":
                skipped += 1
                print(f"  ○ {name} — skipped（{e}）")
                continue
            if not isinstance(e, Exception):           # KeyboardInterrupt 之类照旧上抛
                raise
            failed += 1
            print(f"  ✗ {name} — {type(e).__name__}: {e}")
            if str(e) not in ("", "None"):
                traceback.print_exc(limit=3)
    print(f"\n结果：{passed} 通过，{skipped} 跳过，{failed} 失败")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
