---
name: auto-get-py
description: Auto-Get-PY 媒体爬取器 — 通过 API 触发网页媒体资源爬取/下载
tags: [scraper, media, download, crawler]
triggers:
  - 爬取
  - 抓取
  - 下载图片
  - 下载视频
  - scrape
  - crawl
  - 抓图
  - 批量下载
  - 爬图
  - 爬视频
---

# Auto-Get-PY Media Scraper

本地运行的网页媒体爬取器，服务地址 `http://localhost:8000`。

## API 端点总览

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/hermes/scrape` | POST | 全功能爬取（可等待完成） |
| `/api/hermes/quick` | POST | 仅发现 URL，不下载 |
| `/api/hermes/status/{id}` | GET | 查询任务状态 |
| `/api/hermes/results/{id}` | GET | 获取完成结果 |
| `/api/hermes/cancel/{id}` | POST | 取消任务 |

## 标准工作流

### 1. 快速探测（先看看有什么）

```bash
curl -s http://localhost:8000/api/hermes/quick \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "目标URL",
    "crawl_depth": 2,
    "max_pages": 100,
    "follow_pagination": true
  }' | python3 -m json.tool
```

返回 `urls` 数组就是发现的所有媒体链接。用于：
- 先预览再决定是否下载
- 把 URL 列表交给其他工具处理

### 2. 全量爬取（触发下载）

```bash
curl -s http://localhost:8000/api/hermes/scrape \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "目标URL",
    "name": "任务名称",
    "crawl_depth": 3,
    "max_pages": 500,
    "follow_pagination": true,
    "follow_links": true,
    "wait": false
  }'
```

返回 `task_id`，然后轮询状态。

### 3. 同步等待模式（适合简单任务）

```bash
curl -s http://localhost:8000/api/hermes/scrape \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "目标URL",
    "wait": true,
    "wait_timeout": 120
  }'
```

直接返回最终结果，包含 `completed_files` 列表。

### 4. 查询状态

```bash
curl -s http://localhost:8000/api/hermes/status/{task_id}
```

返回：`status`（running/completed/failed）、`downloads` 统计、进度。

### 5. 获取结果

```bash
curl -s http://localhost:8000/api/hermes/results/{task_id}
```

返回：`completed_files`（文件名+大小+路径）、`failed_files`、统计。

## 完整参数参考

### ScrapeRequest

```
url              string   必填，目标URL
name             string   任务名（默认 "Hermes Agent Task"）
crawl_depth      int      爬取深度 0-20（默认 0=单页）
max_pages        int      最大页面数（默认 200）
follow_pagination bool    自动翻页（默认 true）
follow_links     bool     跟踪链接（默认 false）
allowed_paths    string[] 限制路径前缀如 ["/gallery/"]
use_browser      bool     Playwright 渲染JS页面（默认 false）
crawl_css        bool     爬CSS文件（默认 true）
crawl_iframes    bool     爬iframe（默认 true）
site_discovery   bool     sitemap/robots/RSS发现（默认 false）
extract_base64   bool     提取内联base64图片（默认 false）
file_types       string[] 文件类型过滤如 ["jpg","mp4"]
concurrency      int      并发数 1-50（默认 5）
request_delay_sec float   请求间隔秒（默认 0.5）
request_timeout_sec int   超时秒（默认 30）
max_retries      int      重试次数（默认 3）
proxy            string   代理URL
custom_headers   dict     自定义请求头
decryptors       string[] 解密器列表
output_dir       string   输出目录（默认 "./downloads"）
max_file_size_mb int      最大文件MB（默认 500）
wait             bool     同步等待完成
wait_timeout     int      等待超时秒（默认 300）
```

## 使用决策树

用户说"帮我爬 XXX 的图片"时：

1. **先探测**：用 `/api/hermes/quick` 看有多少资源
2. **展示结果**：告诉用户发现了什么、多少个文件
3. **确认后下载**：用户同意后用 `/api/hermes/scrape` 触发
4. **跟踪进度**：轮询 `/api/hermes/status/{id}` 报告进度
5. **汇报结果**：完成后用 `/api/hermes/results/{id}` 展示下载列表

## 常见场景模板

### 图库网站
```json
{"url": "https://xxx.com/gallery/", "crawl_depth": 2, "follow_pagination": true, "file_types": ["jpg","png","webp"]}
```

### 视频站
```json
{"url": "https://xxx.com/video/123", "use_browser": true, "file_types": ["mp4","m3u8","webm"]}
```

### 整站镜像
```json
{"url": "https://xxx.com/", "site_discovery": true, "crawl_depth": 5, "max_pages": 10000, "follow_links": true, "follow_pagination": true}
```

### JS 重的 SPA 站
```json
{"url": "https://xxx.com/", "use_browser": true, "crawl_depth": 3, "max_scrolls": 50}
```

### 需要代理
```json
{"url": "https://xxx.com/", "proxy": "http://127.0.0.1:7890", "crawl_depth": 2}
```

### Direct 模式（推荐用于 JS 站点）

`POST /api/hermes/direct` — 绕过引擎，Playwright 渲染 + 直接下载，同步返回结果。

```bash
curl -s http://localhost:8000/api/hermes/direct \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://m.baidu.com",
    "max_scrolls": 3,
    "timeout": 20,
    "concurrency": 10,
    "file_types": ["jpg", "png", "gif", "webp"],
    "output_dir": "./downloads/baidu"
  }'
```

返回完整结果：`media_found`, `completed`, `failed`, `files[]`, `errors[]`。

**适用场景**：SPA 站点、JS 动态加载、需要浏览器渲染的页面。
**比 scrape 更可靠**：直接在请求线程中完成，无并发信号量问题。

## 注意事项

- 服务默认运行在 `localhost:8000`，先用 health 端点确认在线
- `use_browser` / `direct` 端点需要 playwright：`pip install playwright && playwright install chromium`
- 下载的文件在 `~/Auto-Get-PY/downloads/` 目录
- 大规模爬取建议设 `request_delay_sec >= 0.5` 避免被封
- 中文 URL 和文件名已全面支持 Unicode
- **JS 站点优先用 `/api/hermes/direct`**，比 `/api/hermes/scrape` + `use_browser` 更可靠
