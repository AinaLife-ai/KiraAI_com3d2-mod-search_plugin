# 测试说明（com3d2-mod-search）

离线可跑、无外部依赖，覆盖插件自身的逻辑（框架无关）。

```bash
# 1) 不依赖任何第三方包
python tests/run_tests.py

# 2) 装了 pytest 也可以（同一批用例，函数名 test_*）
python -m pytest tests -q

# 3) 额外跑一次真实 Mukuu 搜索（默认关，避免 CI/离线环境卡住）
C3D_LIVE=1 python tests/run_tests.py

# 4) 想用真 KiraAI 框架而不是内置桩
KIRA_CORE=/path/to/kira/core python tests/run_tests.py
```

## 设计约定（为什么它可以随便在哪跑）

| 约定 | 说明 |
| --- | --- |
| **零硬编码** | 不写死任何路径（插件根由 `__file__` 反推）、版本（读 `manifest.json`）、关键词（从 `tier_map.TIER_MAP` 里取）、日期或条数 |
| **零第三方依赖** | 没有 `httpx` 时自动注入最小假实现；`playwright` 缺失时相关断言自动转为「降级路径」验证 |
| **框架无关** | 没有真 KiraAI core 时安装 `_stub_core` 最小桩（只实现插件用到的表层 API），有真框架则用真的 |
| **默认不联网** | 联网用例需显式 `C3D_LIVE=1`；其余全部使用合成数据 |
| **不碰真磁盘** | 输出/缓存一律写在 `tempfile.TemporaryDirectory()` 里 |

## 用例一览

| 用例 | 覆盖 |
| --- | --- |
| `test_manifest_fields` / `test_schema_shape` / `test_notify_empty_default_off` / `test_tool_params_use_json_schema_enum` | 元数据与配置形态：schema 必须是 `section`+`fields`（框架按顶层键解析）、字段必有 `type`/`name`、不得使用已废弃的 `enum` 类型、`notify_empty` 默认关 |
| `test_tier_map_structure` / `test_tier_map_noise_and_fallback` | 三梯级转换：梯级名不重复、噪音词剥离、表外词原样返回、空输入安全 |
| `test_parse_post_and_download_links` / `test_serialize_items_is_compact_json` | 帖子解析与链接白名单（含**链接尾部中英标点剥离**）、给 LLM 的紧凑 JSON |
| `test_cache_key_includes_limit_and_ttl` / `test_client_reuse_and_close` / `test_post_retries_once_after_broken_client` | 缓存键含 `limit`、TTL 过期重取、HTTP 客户端复用/关闭/重建、连接坏掉后重试一次 |
| `test_empty_result_matrix` / `test_hit_path_unchanged` | **空结果策略**：工具路径默认不插话、开关打开=旧行为、命令路径极简提示、两种开关下返回给 LLM 的内容完全一致；有结果时照常合并转发 |
| `test_pagination_advances_from_stored_offset` | 翻页从「下一页偏移」继续（防回归：旧实现会跳过一整页） |
| `test_adapter_identity_reading` | 机器人账号/昵称从适配器配置读、按目标会话选适配器、未知适配器回退 |
| `test_png_pruning` | 渲染产物只保留最新 N 张 |
| `test_render_degrades_without_playwright` / `test_render_stays_per_render` | 缺 playwright 时明确降级；**防回归：渲染保持「每次开→关」，不得引入常驻浏览器** |
| `test_static_wiring` | 发送走 `ctx.send_message_chain`、不读两代都不存在的适配器属性、异步路径无 `time.sleep` |
| `test_live_search_opt_in` | （可选）真实 Mukuu 搜索：只校验返回**结构**，不校验具体数据 |
