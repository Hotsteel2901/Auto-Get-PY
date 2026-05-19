# Auto-Get-PY

> 通用网页爬取器，支持媒体文件下载、可插拔解密器、本地 Web UI 管理面板。

**AI 生成项目** — 此代码库由 Claude Code (Anthropic) 通过迭代设计、实现和审查周期生成。人工提供需求和方向，AI 生成所有代码、测试、文档和提交。

---

## 功能特性

- **通用媒体下载** — 图片 (jpg, png, gif, webp, avif, heic...)、视频 (mp4, mkv, webm, ts, m3u8...)、音频 (mp3, flac, aac, ogg...)、文档 (pdf, docx, epub...)、压缩包 (zip, rar, 7z...)
- **可插拔解密器管道** — Base64、Hex、AES (CBC/ECB/GCM)、XOR、ROT47、URL 签名剥离、自定义 Python 表达式
- **异步并发下载** — 可配置并发数，分块传输带进度追踪
- **断点续传** — HTTP Range 头部支持中断下载恢复
- **自动重试** — 指数退避 (1s, 2s, 4s...)，可配置最大重试次数
- **暗色主题 Web UI** — SPA 仪表盘，WebSocket 实时进度，任务管理，文件浏览，设置管理
- **SQLite 持久化** — 任务、下载记录和设置在重启后保留
- **一条命令启动** — `python app.py` 启动一切

---

## 快速开始

### 环境要求

- Python 3.10+
- pip

### 安装

```bash
git clone https://github.com/Hotsteel2901/Auto-Get-PY.git
cd Auto-Get-PY
pip install -r requirements.txt
```

### 运行

```bash
python app.py
# 自定义端口:
python app.py --port 9090
# 开发模式（热重载）:
python app.py --reload
```

在浏览器中打开 **http://localhost:8000**。

---

## Web UI 使用指南

侧边栏包含 5 个页面：

### 1. 仪表盘 (Dashboard)

首页，展示：

- **统计卡片** — 运行中 / 已完成 / 失败 任务数量
- **最近任务** — 表格包含进度条、暂停/恢复/重试按钮
- **实时更新** — 所有统计数据通过 WebSocket 随下载进度自动刷新

### 2. 新建任务 (New Task)

创建爬取任务：

| 区域 | 说明 |
|------|------|
| 任务名称 | 给任务起个标签名 |
| 目标 URL | 要爬取媒体链接的网页地址 |
| 文件类型过滤 | 按分类勾选/取消扩展名（图片 / 视频 / 音频 / 文档 / 压缩包）。底部可输入自定义扩展名。 |
| 解密器 | 启用解密层。AES 和 XOR 有可展开的密钥配置面板。自定义允许输入 Python 表达式。 |
| 高级选项 | 并发数 (1-20)、请求延迟、超时、最大重试、最大文件大小、输出目录 |
| 自定义请求头 | 添加 HTTP 头部（如 Referer、User-Agent、Authorization） |

点击 **Start Scraping** — 任务创建后立即开始执行。

### 3. 下载列表 (Downloads)

浏览所有任务的下载结果：

- **按任务筛选** 通过下拉菜单
- **按文件名搜索**
- 每行显示：文件名、文件大小、状态标签、进度条、时间
- **Download** 按钮下载已完成文件
- 失败下载显示错误信息

### 4. 设置 (Settings)

持久化到 SQLite 的全局默认值：

- 默认并发数
- 默认输出目录
- AES 密钥和 IV（十六进制编码），可在任务间复用

### 5. 文件浏览 (Files)

浏览所有已下载到磁盘的文件。按修改时间排序（最新在前）。点击 **Download** 本地下载文件。

---

## 解密器参考

解密器按**优先级顺序**在管道中运行。第一个 `can_handle()` 检查通过的解密器处理内容。管道最多迭代 3 轮。

| 解密器 | 优先级 | 配置 | 使用场景 |
|--------|--------|------|----------|
| **Base64** | 10 | 无 | 页面源码中的 Base64 编码媒体 URL |
| **Hex** | 10 | 无 | 十六进制编码字符串 |
| **AES** | 20 | key (hex), iv (hex), mode (CBC/ECB/GCM) | 已知密钥的 AES 加密内容 |
| **XOR** | 30 | key (hex) | 简单 XOR 混淆数据 |
| **URL Sign** | 40 | 无（可选：额外参数名） | 从 URL 中剥离 `sign`、`token`、`expires` 等签名参数 |
| **ROT47** | 50 | 无 | 页面源码中的 ROT47 编码文本 |
| **Custom** | 100 | Python 表达式 | 用户自定义转换。`content` 为字节变量。示例：`bytes(b ^ 0xFF for b in content)` |

**自定义解密器安全提示：** 基于 `eval()` 的自定义表达式在 Python 进程中无沙箱运行。仅限可信本地使用。

---

## CLI 命令行参考

```
python app.py [options]

选项:
  --host HOST     绑定主机地址 (默认: 0.0.0.0)
  --port PORT     绑定端口 (默认: 8000)
  --reload        启用 uvicorn 自动重载（开发模式）
```

### 使用示例

```bash
# 基本用法
python app.py

# 局域网可访问
python app.py --host 0.0.0.0 --port 8080

# 开发模式热重载
python app.py --reload
```

---

## API 接口概览

所有接口位于 `/api/` 路径下。

### 任务 (Tasks)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks` | 任务列表（查询参数: `status`, `offset`, `limit`） |
| POST | `/api/tasks` | 创建任务 (`{name, url, config}`) |
| GET | `/api/tasks/{id}` | 任务详情 |
| PUT | `/api/tasks/{id}` | 更新任务配置 |
| DELETE | `/api/tasks/{id}` | 删除任务及关联下载 |
| POST | `/api/tasks/{id}/start` | 开始爬取 |
| POST | `/api/tasks/{id}/pause` | 暂停 |
| POST | `/api/tasks/{id}/resume` | 恢复 |
| POST | `/api/tasks/{id}/retry` | 重试所有失败下载 |

### 下载 (Downloads)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks/{id}/downloads` | 某任务的下载列表（查询参数: `status`） |

### 设置 (Settings)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/settings` | 获取所有设置 |
| PUT | `/api/settings` | 更新设置（键值对字典） |

### 文件 (Files)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/files` | 浏览已下载文件（查询参数: `dir`） |
| GET | `/api/files/download/{filename}` | 本地下载文件 |

### WebSocket

| 路径 | 说明 |
|------|------|
| `/ws/progress` | 实时进度推送: `{task_id, done, total, current_file, speed}` |

---

## 任务配置参考

任务创建时的 `config` 字段接受以下 JSON 结构：

```json
{
  "concurrency": 5,
  "output_dir": "./downloads",
  "decryptors": ["base64", "aes"],
  "decryptor_opts": {
    "aes": {"key": "your-hex-key", "iv": "your-hex-iv", "mode": "cbc"}
  },
  "url_filters": {
    "include": ["*.jpg", "*.mp4", "*.pdf"],
    "exclude": ["*.gif"]
  },
  "custom_headers": {
    "Referer": "https://example.com",
    "User-Agent": "Mozilla/5.0 ..."
  },
  "request_delay_sec": 0.5,
  "request_timeout_sec": 30,
  "max_retries": 3,
  "max_file_size_mb": 500
}
```

---

## 项目结构

```
Auto-Get-PY/
├── app.py                         # FastAPI 入口 + CLI
├── scraper/
│   ├── engine.py                  # 编排器: 抓取 → 解密 → 提取 → 下载
│   ├── extractor.py               # 从 HTML 提取媒体 URL
│   ├── downloader.py              # 异步分块下载 + 断点续传
│   ├── task_manager.py            # 生命周期、并发控制、暂停/恢复
│   └── decryptors/
│       ├── base.py                # BaseDecryptor 抽象基类 + 注册器 + 管道
│       ├── base64_dec.py          # Base64 解码器
│       ├── hex_dec.py             # Hex 解码器
│       ├── aes_dec.py             # AES-CBC/ECB/GCM 解码器
│       ├── xor_dec.py             # XOR 解码器
│       ├── url_sign_dec.py        # URL 签名参数剥离器
│       ├── rot47_dec.py           # ROT47 字符移位
│       └── custom_dec.py          # 用户自定义 Python 表达式
├── db/
│   ├── schema.py                  # SQLite 建表 + init_db
│   └── queries.py                 # 异步查询函数
├── api/
│   ├── tasks.py                   # 任务 CRUD + 控制路由
│   ├── downloads.py               # 下载列表路由
│   ├── settings.py                # 设置读/写路由
│   ├── files.py                   # 文件浏览 + 下载服务
│   └── websocket.py              # WebSocket 进度推送
├── webui/
│   ├── index.html                 # SPA 外壳
│   ├── css/style.css              # 暗色主题设计系统
│   └── js/
│       ├── app.js                 # 路由器 + WebSocket + 工具函数
│       ├── api.js                 # REST API 客户端
│       ├── dashboard.js           # 仪表盘页面
│       ├── task-form.js           # 新建任务表单
│       ├── downloads.js           # 下载浏览器
│       ├── settings.js            # 设置页面
│       └── files.js               # 已下载文件浏览器
├── tests/                         # 29 个通过的测试
├── downloads/                     # 默认输出目录
└── requirements.txt               # Python 依赖
```

---

## 依赖项

| 包 | 用途 |
|----|------|
| fastapi | Web 框架 + API |
| uvicorn | ASGI 服务器 |
| aiohttp | 异步 HTTP 客户端（爬取/下载） |
| aiofiles | 异步文件 I/O |
| aiosqlite | 异步 SQLite |
| pydantic | 请求参数校验 |
| pycryptodome | AES 解密 |
| httpx | 测试客户端 |

---

## 测试

```bash
pip install httpx
python -m pytest tests/ -v
```

29 个测试覆盖：全部 7 个解密器、URL 提取器、异步下载器（模拟）、API 接口、任务生命周期。

---

## 限制与边界

这是一个**本地优先、单用户**的工具。以下功能有意不包含在内：

- 多用户认证 / 登录
- 分布式爬取（Celery、Redis）
- 浏览器自动化（Playwright/Selenium 处理 JS 渲染页面）
- OCR 验证码识别
- 自定义表达式沙箱隔离（默认本地可信环境）

---

## 许可证

MIT

---

[English Version (英文版)](README.md)

*由 Claude Code (deepseek) (Anthropic) 生成 — 2026 年 5 月*
