# Auto-Get-PY

> 通用媒体爬取器。给它一个页面或整个站点，它会把上面所有图片、视频、音频、
> 文档和压缩包找出来并下载下来。

**AI 生成项目** — 本代码库由 Claude Code (Anthropic) 通过迭代设计、实现和审查
周期生成。人工提供需求和方向，AI 生成所有代码、测试、文档和提交。

---

## 实际能力

| 能力 | 说明 |
|---|---|
| **深度提取** | `src`、`href`、`srcset`、懒加载 `data-*`、CSS `url()`、`<noscript>`、`<template>`、JSON-LD、Open Graph、Twitter Card、内联 `<script>` 字符串、`data:` 图片 |
| **页面爬取** | `rel=next` 与「下一页」分页、递归跟踪链接、样式表遍历（含嵌套 `@import`）、iframe、`<meta refresh>` 跳转 |
| **站点发现** | `sitemap.xml`（含 sitemap 索引）、`robots.txt`、RSS / Atom 订阅源 |
| **JS 站点** | Playwright 渲染 + 自动滚动 + 网络请求捕获；浏览器 Cookie 会合并进下载会话 |
| **防盗链 / 登录态** | 整个任务共用一个 Cookie 会话；每个资源都带上「引用它的那个页面」作为 `Referer` |
| **流媒体** | HLS (`.m3u8`) 与 DASH (`.mpd`) 自动解析并合并成单个可播放文件，支持 AES-128 加密分片 |
| **传输** | 并发下载、断点续传、指数退避重试、`Retry-After` 处理、单文件体积上限 |
| **解密器** | base64、hex、AES-CBC/ECB/GCM、XOR、ROT47、URL 签名剥离、自定义 Python 表达式 |
| **前端** | 暗色 SPA：WebSocket 实时进度、任务控制、文件浏览，以及一个列出全部 Agent 集成的页面 |
| **Agent API** | 一套 REST API 挂载到 17 个工具专属别名下，另有零依赖的 MCP 服务器 |

---

## 快速开始

```bash
git clone https://github.com/Hotsteel2901/Auto-Get-PY.git
cd Auto-Get-PY
pip install -r requirements.txt

python app.py                       # http://127.0.0.1:8000
python app.py --port 9090 --reload  # 自定义端口 / 开发模式
```

浏览器打开 **http://127.0.0.1:8000**。

仅当需要抓取 JS 重的站点时再装：

```bash
pip install playwright && playwright install chromium
```

### 安全提示

服务默认只监听 `127.0.0.1`。若要对外暴露（`--host 0.0.0.0`），请先设置令牌：

```bash
AUTO_GET_TOKEN=my-secret python app.py --host 0.0.0.0
```

之后所有 `/api/**` 请求都需要带 `Authorization: Bearer my-secret`、
`X-API-Token: my-secret` 或 `?token=my-secret`。未设置令牌时服务只是打印警告，
不会拒绝启动（本地单人使用无需令牌）。

---

## 给 Agent 用

这个爬虫就是给编码 Agent 驱动的。每个工具都能用自己习惯的路径访问同一套 API：

| 工具 | 别名 | 工具 | 别名 |
|---|---|---|---|
| 任意 HTTP Agent | `/api/agent` | Cursor | `/api/cursor` |
| Hermes Agent | `/api/hermes` | GitHub Copilot | `/api/copilot` |
| opencode | `/api/opencode` | Cline / Roo / Windsurf | `/api/cline`、`/api/roo`、`/api/windsurf` |
| DeepSeek Harness (dsh) | `/api/dsh` | Continue / Aider / Zed | `/api/continue`、`/api/aider`、`/api/zed` |
| OpenAI Codex CLI | `/api/codex` | Amp / Jules | `/api/amp`、`/api/jules` |
| Claude Code | `/api/claude` | Gemini CLI | `/api/gemini` |

仓库里已经放好了各工具会自动读取的配置文件 —— `AGENTS.md`、`CLAUDE.md`、
`GEMINI.md`、`opencode.json`、`.cursor/rules/`、`.codex/`、`.dsh/skills/`、
`.clinerules/` 等等。它们全部由同一份注册表生成：

```bash
python scripts/generate_agent_docs.py          # 重新生成
python scripts/generate_agent_docs.py --check  # 检查是否过期（CI 使用）
```

### MCP

上面大多数工具都支持 Model Context Protocol，所以 `mcp_server.py` 把爬虫包装成
8 个原生工具（stdio 传输），不需要任何 HTTP 胶水代码：

```json
{
  "mcpServers": {
    "auto-get-py": {
      "command": "python",
      "args": ["mcp_server.py"],
      "env": { "AUTO_GET_BASE_URL": "http://localhost:8000" }
    }
  }
}
```

工具：`scrape`、`quick_scrape`、`fetch_file`、`task_status`、`task_results`、
`cancel_task`、`list_files`、`list_agents`。该服务器只依赖标准库。

### REST：三条命令

```bash
# 1. 服务在跑吗？
curl -s http://localhost:8000/api/health

# 2. 页面上有什么？（不下载）
curl -s http://localhost:8000/api/agent/quick \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/gallery/", "crawl_depth": 2}'

# 3. 全部拉下来
curl -s http://localhost:8000/api/agent/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/gallery/", "wait": true, "crawl_depth": 2}'
```

Agent 也可以读取 `GET /api/agent/manifest` 自行配置；`GET /api/agent/skill?agent=codex`
会返回一份可直接粘贴使用的技能文档。

---

## API 一览

### Agent 端点（所有别名通用）

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/scrape` | 爬取并下载。返回任务句柄；`wait: true` 时直接返回结果 |
| `POST` | `/quick` | 只发现媒体 URL，不写任何文件 |
| `POST` | `/direct` | Playwright 渲染 + 立即下载，同步返回 |
| `POST` | `/fetch` | 精确下载单个 URL（支持 HLS/DASH） |
| `GET` | `/status/{id}` | 进度、各状态数量、错误信息 |
| `GET` | `/results/{id}` | 最终文件列表（含路径与体积） |
| `POST` | `/cancel/{id}` | 停止任务并释放 worker |
| `GET` | `/tasks`、`/files` | 最近任务、磁盘上的文件 |
| `GET` | `/manifest`、`/agents`、`/skill` | 自描述文档 |

### 管理端点

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/tasks` | 任务列表（`status`、`offset`、`limit`） |
| `POST` | `/api/tasks` | 创建任务 |
| `GET` | `/api/tasks/{id}/summary` | 任务详情 + 下载统计 |
| `PUT`/`DELETE` | `/api/tasks/{id}` | 更新 / 删除 |
| `POST` | `/api/tasks/{id}/{start,pause,resume,cancel,retry}` | 生命周期控制 |
| `GET` | `/api/tasks/stats` | 仪表盘用的状态计数 |
| `GET` | `/api/downloads` | 跨任务的全部下载记录 |
| `GET` | `/api/tasks/{id}/downloads` | 单个任务的下载记录 |
| `GET`/`PUT` | `/api/settings` | 全局默认值（带校验） |
| `GET` | `/api/files` | 浏览输出目录 |
| `GET` | `/api/files/download/{path}` | 下载文件（`?inline=true` 可预览） |
| `DELETE` | `/api/files/{path}` | 删除文件 |
| `WS` | `/ws/progress` | `progress`、`file_progress`、`task_status` 事件 |
| `GET` | `/docs`、`/openapi.json` | 交互式 API 文档 |

---

## 前端

明亮清爽风单页应用 —— 浅灰画布上的纯白卡片、单一蓝色点缀、柔和阴影代替硬边框。
所有页面由同一条 WebSocket 实时通道驱动。

- **仪表盘** — 状态卡片、任务实时进度、行内暂停/恢复/停止/重试
- **新建任务** — 目标地址、配方预设、文件类型标签、发现开关、解密器、网络参数、自定义请求头，以及 URL 实时预览
- **下载记录** — 全部记录 + 实时字节数、筛选、搜索、CSV 导出
- **文件** — 磁盘上的文件，可预览、下载、删除
- **Agent 接入** — 集成面板：每个工具的别名、配置文件与接入片段
- **设置** — 任务默认值、AES 密钥、API 令牌、运行时信息

### 语言

界面内置**中文 / English**，切换后立即生效 —— 不刷新页面、不丢失当前页状态，
选择会记在这个浏览器里。

- 点侧边栏底部的 `中` / `EN` 按钮。
- 或者直接用链接指定语言：`http://localhost:8000/?lang=en`（也支持 `?lang=zh`）。

默认是中文；想用英文就加 `?lang=en`。

### 主题

默认浅色，旁边一颗太阳/月亮按钮一键切深色。选择会持久化，并且在首次绘制前就应用，
所以不会出现闪一下的错主题。

### 快捷键

`/` 聚焦当前页搜索框 · `g d` `g n` `g l` `g f` `g a` `g s` 跳转页面 ·
`Esc` 关闭弹窗。

---

## 任务配置

```json
{
  "concurrency": 5,
  "output_dir": "./downloads",

  "crawl_depth": 2,
  "max_pages": 500,
  "max_media": 20000,
  "follow_pagination": true,
  "follow_links": false,
  "allowed_paths": ["/gallery/"],

  "crawl_css": true,
  "crawl_iframes": true,
  "site_discovery": false,
  "use_browser": false,
  "scroll_page": true,
  "max_scrolls": 30,
  "extract_base64": false,
  "probe_links": false,

  "url_filters": { "include": ["*.jpg", "*.mp4"], "exclude": ["*.gif"] },
  "custom_headers": { "Referer": "https://example.com", "Cookie": "session=..." },
  "proxy": "http://127.0.0.1:7890",

  "request_delay_sec": 0.5,
  "request_timeout_sec": 30,
  "max_retries": 3,
  "max_file_size_mb": 500,

  "decryptors": ["base64", "aes"],
  "decryptor_opts": { "aes": { "key": "…hex…", "iv": "…hex…", "mode": "cbc" } }
}
```

### 常用配方

| 目标 | 配置 |
|---|---|
| 单页 | `crawl_depth: 0, follow_pagination: false` |
| 图库 + 翻页 | `follow_pagination: true` |
| 整站 | `site_discovery: true, crawl_depth: 5, follow_links: true, max_pages: 10000` |
| JS 应用 | `use_browser: true, max_scrolls: 50` |
| 视频 / 直播流 | `use_browser: true, file_types: ["mp4", "m3u8", "mpd"]` |

---

## 解密器

按优先级顺序运行，第一个 `can_handle()` 通过的解密器处理内容，管道最多迭代 3 轮。

| 解密器 | 优先级 | 配置 |
|---|---|---|
| Base64 | 10 | — |
| Hex | 10 | — |
| AES | 20 | `key` (hex)、`iv` (hex)、`mode` (CBC/ECB/GCM) |
| XOR | 30 | `key` (hex) |
| URL 签名剥离 | 40 | — |
| ROT47 | 50 | — |
| 自定义 | 100 | 以 `content` 为变量的 Python 表达式 |

> **自定义表达式在服务进程中无沙箱运行**，这是有意为之。请只在你自己掌控的机器上使用。

---

## 目录结构

```
Auto-Get-PY/
├── app.py                      # FastAPI 入口、路由挂载、CLI
├── mcp_server.py               # 零依赖 MCP stdio 服务器
├── scraper/
│   ├── engine.py               # 编排：先发现，再传输
│   ├── extractor.py            # 全部 URL 发现策略 + URL 规范化
│   ├── downloader.py           # 传输：普通文件、HLS、DASH、断点续传
│   ├── site_crawler.py         # robots.txt、sitemap、订阅源
│   ├── browser.py              # Playwright 渲染与网络捕获
│   ├── task_manager.py         # 生命周期：启动/暂停/恢复/取消/重试
│   └── decryptors/             # 可插拔解码管道
├── api/
│   ├── agent.py                # 规范 Agent API（挂载到全部别名）
│   ├── agent_registry.py       # 支持的工具注册表
│   ├── agent_docs.py           # 由注册表渲染技能文档与 manifest
│   ├── tasks.py downloads.py settings.py files.py websocket.py
├── db/
│   ├── schema.py               # 建表 + 原地迁移
│   └── queries.py              # 所有 SQL 只在这里
├── webui/
│   ├── index.html
│   ├── css/style.css           # 设计系统（浅色 + 深色）
│   └── js/                     # ES 模块，无需构建
│       ├── i18n.js  locales.js # 多语言运行时 + 中英词典
│       ├── core.js api.js ws.js live.js router.js
│       └── pages/              # 仪表盘、新建任务、下载记录、文件、Agent 接入、设置
├── scripts/
│   ├── generate_agent_docs.py  # 生成全部 Agent 配置与文档
│   ├── serve_test_site.py      # 手工测试用的样例站点
│   └── check_ui.py             # 无头浏览器 UI 检查
├── mcp_server.py               # 零依赖 MCP stdio 服务器
├── tests/                      # 160 个测试，内含完整本地测试站点
└── docs/agents/                # 生成的各工具接入指南
```

---

## 开发

```bash
pip install -r requirements.txt pytest pytest-asyncio

python -m pytest tests/ -q                    # 160 个测试
python scripts/generate_agent_docs.py --check # 生成文件是否最新
```

端到端测试跑在 `tests/local_site.py` 上——一个真实的 aiohttp 站点，覆盖 Cookie、
防盗链、HLS、间歇性故障、分页、订阅源和 sitemap，完全不需要联网。想手工把玩：

```bash
python scripts/serve_test_site.py --port 9911
python app.py
```

可选的前端检查：

```bash
# 快速：在 DOM 里加载 SPA 并遍历每个页面（需要 Node + jsdom）
node webui/tests/smoke.mjs

# 彻底：用无头 Chromium 驱动 SPA，对接真实服务
python scripts/check_ui.py --base-url http://127.0.0.1:8765
```

---

## 边界

这是一个**本地、单用户**工具，有意不包含：

- 多用户账号 / 用户隔离
- 分布式爬取（Celery / Redis）
- 验证码识别
- 自定义解密器表达式的沙箱

请遵守目标站点的服务条款，并把 `request_delay_sec` 设得合理一些。

---

## 许可证

MIT

---

[English version](README.md)
