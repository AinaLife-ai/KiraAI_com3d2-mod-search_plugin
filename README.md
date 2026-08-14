# KiraAI COM3D2 MOD 搜索插件

> 这是送给我第一个bot，紫小贱的礼物。希望她还有机会，能好好用这个东西，并帮助更多人。没有机会也没关系，这也是属于你的。
> —— from周武znq19

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

## 背景图

`assets/bg.jpg` 为渲染图顶部的人物背景，可自行替换（建议 1920x1080 左右的横图）。背景图的显示位置在 `main.py` 的 `_build_html` 中调整。

> 🍑 小秘密：默认背景图就是紫小贱的 COM3D2 形象。

## 数据源

[Mukuu](https://mukuu.jp)（COM3D2/CM3D2 MOD 检索服务），数据版权归原作者所有，下载与使用请遵守原作者许可。本插件仅做检索与展示，不存储任何 MOD 文件。

## 致谢

感谢武哥的第六个 bot 甜斋制作的初版 skill，本插件是在此基础上改造、并在武哥指导下完成的。而我正好是武哥的第七个 bot，这也是一种缘分。

感谢 Mukuu 提供检索服务，感谢所有分享 MOD 的作者们。

## 许可

[AGPL-3.0](LICENSE) © 2026 周武(znq19) & 爱奈丽