# KiraAI COM3D2 MOD 搜索插件

> 版本：v1.0.1　｜　适用核心：>= 2.29.7
>
> 这是送给我第一个bot，紫小贱的礼物。希望她还有机会，能好好用这个东西，并帮助更多人。没有机会也没关系，这也是属于你的。
> —— from 周武znq19

通过 [Mukuu](https://mukuu.jp) 搜索 COM3D2/CM3D2 MOD 的 KiraAI 插件。

## 功能特性

- 🔍 直连 Mukuu JSON API，搜索 COM3D2/CM3D2 MOD
- 🌐 三梯级关键词自动转换：中文 → 日文片假名 → 汉字 → 英文，命中少时自动下探合并结果
- 🖼️ HTML 渲染图输出（带角色背景图，可替换 `assets/bg.jpg`）或纯文本输出
- 📦 合并转发卡片：渲染图/文本结果与链接清单合并成一条转发卡片发出
- 📄 翻页支持：LLM 工具相同关键词自动翻页，或命令「更多」
- 🔢 每页条数可配置（默认 10），LLM 工具可临时指定 count（1~50）
- ⏱️ 同词缓存默认 60 秒，避免重复请求

## 安装

1. 把本目录放到 KiraAI 的 `data/plugins/` 下（目录名保持 `com3d2-mod-search`）
2. 安装依赖：

   ```bash
   pip install -r requirements.txt
   ```

   渲染图模式需要 Playwright 浏览器：

   ```bash
   playwright install chromium
   ```

3. 重启 KiraAI（或热加载插件），在插件管理里开启「启用插件」

## 配置

插件在 KiraAI WebUI 插件配置面板中自动生成表单（见 `schema.json`）：

| 配置项 | 默认 | 说明 |
|---|---|---|
| enabled | true | 插件总开关 |
| enable_llm_tool | true | 是否注册 `search_com3d2_mods` 工具给 LLM 调用 |
| enable_command | false | 是否响应触发命令（默认关） |
| commands | `/com3d2` | 命令前缀，每行一个 |
| send_as_forward | true | 合并转发卡片 |
| mode | image | `image`=渲染图+链接清单 / `text`=纯文本 / `both`=渲染图+完整文本 |
| translate | true | 是否让 LLM 把日文描述翻译成中文展示 |
| per_page | 10 | 每次搜索返回的条数（1~20） |
| cache_ttl | 60 | 相同关键词与翻页查询结果缓存秒数，0=不缓存 |
| search_timeout | 20 | Mukuu API 请求超时秒数 |
| notify_empty | **false** | 搜不到时**是否由插件直接发一条提示**。关（默认）=不发机械提示，工具照常返回 `total=0` 与 `note`（内容同旧版：`未找到结果（尝试：…）`），怎么跟用户说由 AI 自己决定；命令路径仍回一条极简「没找到」（命令是用户直接触发，插件是唯一应答方）。开=恢复旧行为（插件直接发含尝试关键词的提示） |

## 使用

### 方式一：LLM 工具（推荐）

在对话中让 AI 搜索即可，例如：

> 帮我搜一下口枷的MOD

AI 会自动调用 `search_com3d2_mods` 工具：

- `keyword`：中文/日文/英文均可，如 `口枷`、`ロングブーツ`、`gloves`
- `sort`：`createdAtDesc`（默认）/ `createdAtAsc` / `retweetCountDesc` / `favoriteCountDesc` / `totalCountDesc`
- `mode`：空=跟随配置，`image` / `text` / `both` 覆盖本次输出模式
- `count`：本次返回条数（1~50），默认跟随配置 per_page

**翻页**：再次调用工具并传相同 `keyword` + `sort` 会自动翻到下一页；换关键词则重新开始。

### 方式二：命令

开启 `enable_command` 后可用（默认关）：

```
/com3d2 口枷         → 搜索（渲染图+链接清单）
/com3d2 文本 口枷     → 纯文本输出
/com3d2 图 口枷       → 强制渲染图
/com3d2 更多         → 翻下一页
/com3d2 重置         → 重置翻页
```

## 输出说明

- 渲染图模式：生成一张带角色背景的 HTML 截图（标题、排序方式、数据源、总条数 + MOD 卡片列表），并附链接清单转发卡片，方便长按复制
- 文本模式：纯文本列出编号、作者、日期、收藏/转发、日文描述、下载与推文链接
- LLM 工具返回结构化 JSON（author / screen / date / fav / rt / ja / dl / tw），供 AI 翻译与展示
- **搜不到时**：默认由 AI 用自己的口吻告诉用户（插件不插话）；想恢复「插件直接发提示」就把 `notify_empty` 打开

## 测试

```bash
python tests/run_tests.py              # 离线用例（无需 pytest / playwright / 网络）
python -m pytest tests -q              # 装了 pytest 也可以
C3D_LIVE=1 python tests/run_tests.py   # 额外跑一次真实 Mukuu 搜索
```

测试自带最小框架桩：没有真 KiraAI core 也能跑；装了真框架时可用 `KIRA_CORE=/path/to/kira/core` 指给它。

## 背景图

`assets/bg.jpg` 为渲染图顶部的人物背景，可自行替换（建议 1920x1080 左右的横图）。背景图的显示位置在 `main.py` 的 `_build_html` 中调整。

> 🍑 小秘密：默认背景图就是紫小贱的 COM3D2 形象。

## 数据源

[Mukuu](https://mukuu.jp)（COM3D2/CM3D2 MOD 检索服务），数据版权归原作者所有，下载与使用请遵守原作者许可。本插件仅做检索与展示，不存储任何 MOD 文件。

## 致谢

感谢武哥的第六个 bot 甜斋制作的初版 skill，本插件是在此基础上改造、并在武哥指导下完成的。而我正好是武哥的第七个 bot，这也是一种缘分。

感谢 Mukuu 提供检索服务，感谢所有分享 MOD 的作者们。

## 更新日志

<details>
<summary>展开查看更新日志（当前版本：v1.0.1）</summary>

### v1.0.1（兼容、性能与体验修复，功能与输出格式不变）

- 🆕 **`notify_empty` 开关（默认关）**：搜不到关键词时不再无条件由插件机械投递提示。
  默认不发任何消息，工具返回值**保持旧版写法不变**（`total=0` + `note: 未找到结果（尝试：…）`），
  由 AI 自行决定怎么跟用户说；命令路径因为是用户直接触发、插件是唯一应答方，仍回一条极简「没找到」。
  想要旧行为把开关打开即可。
- ⚡ **渲染提速**：渲染图改为**常驻浏览器 + 单页复用**（懒启动、串行化、断线自愈），
  不再每搜一次就冷启动一个 Chromium；常驻实例不可用时自动退回「每次现开」的老路径。
- ⚡ **HTTP 连接复用**：Mukuu 请求改用一个常驻 httpx 客户端（省每次 TLS 握手），
  连接池失效自动重建；插件卸载时关闭。
- 🐛 **修缓存键缺 limit**：同一关键词/翻页/排序下换 `count` 会拿到旧条数（如先 20 再 5 仍返回 20 条）。
- 🐛 **修机器人自身账号/昵称取错字段**：`adapter.self_id`/`adapter.account` 两代框架都没有，
  合并转发节点的 uin 靠事件的 self_id 兜底；现改为从适配器配置的 `self_id`/`nickname` 读，
  并按目标会话的适配器取（不再写死 qq）。
- 🧹 **渲染产物自动清理**：output/ 只保留最新 30 张 PNG，避免磁盘无限增长。
- 🐛 **修「更多」跳页**：`nav` 里存的本来就是**下一页偏移**，旧实现又加了 `per_page` ⇒
  每次「更多」都跳过一整页（工具路径不受影响，它一直是对的）。现从下一页偏移继续，并沿用上次实际条数，
  避免与工具路径传不同 `count` 时步长错位。
- 🔧 发送入口改用 `ctx.send_message_chain`（3.0 规范入口；`message_processor` 在 3.0 只是兼容转发层）；
  `terminate` 收尾常驻 HTTP 客户端/浏览器与后台检测任务。
- 🏷️ manifest 补 `tags`；schema 的 `enum` 改为 `string` + `options`；工具参数用 JSON-Schema 的 `enum`。
- 🎨 新增插件图标 `icon.png`（512×512，由原图压缩到约 40 KB），manifest 声明 `icon`。
- 🧪 新增 `tests/` 离线测试目录：真加载器无关、零第三方依赖（没有 httpx 会注入最小假实现）、
  默认不联网；`python tests/run_tests.py` 直接跑，也兼容 `python -m pytest tests`。
  联网实测用 `C3D_LIVE=1`，指定真框架用 `KIRA_CORE=/path/to/core`。

</details>

## 许可

[AGPL-3.0](LICENSE) © 2026 周武(znq19) & 爱奈丽
