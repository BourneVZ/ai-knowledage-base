---
name: github-trending
description: 当需要抓取 GitHub Trending 热门项目、查看 GitHub 今天什么火、发现 AI/LLM/Agent 新项目、或过滤 trending 中的 AI 相关仓库时使用
allowed-tools: WebFetch
---

# GitHub Trending

抓取 `github.com/trending`，按 AI 主题标签过滤仓库，输出 JSON 到 stdout。

## 步骤

### 1. 抓取页面

使用 `WebFetch` 获取 `https://github.com/trending`（markdown 格式）。

**完成条件**：页面内容已获取，无论 HTTP 状态码。

### 2. 解析仓库

逐条提取以下字段：

| 字段 | 来源 |
|------|------|
| `name` | 仓库全名（`owner/repo`） |
| `url` | `https://github.com/owner/repo` |
| `stars` | 星标数，整数 |
| `topics` | 主题标签数组 |
| `description` | 项目描述 |

缺失字段 → `null`。

**完成条件**：trending 列表中每个仓库的 5 个字段均已提取。

### 3. 过滤

丢弃 `topics` 与以下关键词 **无交集** 的仓库：`ai`、`llm`、`agent`、`ml`、`machine-learning`、`deep-learning`。

**完成条件**：保留的仓库均命中 ≥1 个关键词，丢弃的仓库均命中 0 个。

### 4. 输出

按输出格式将 JSON 数组写入 stdout。

**完成条件**：stdout 为合法 JSON，每项字段完整，总数 ≤ 50。

## 约束

- 仅 HTML 解析，不调 GitHub API（避免 rate limit）
- 不写文件、不写数据库、不做去重（由调用方处理）
- 失败（抓取、解析异常）→ 输出 `[]`，永不抛异常
- 执行耗时 < 10s
- 输出必须通过以下 JSON Schema 校验

## 输出格式

```json
[
  {
    "name": "owner/repo",
    "url": "https://github.com/owner/repo",
    "stars": 12345,
    "topics": ["ai", "llm"],
    "description": "项目简述"
  }
]
```

| 字段 | 类型 | 必填 |
|------|------|------|
| `name` | string | 是 |
| `url` | string | 是 |
| `stars` | integer | 是 |
| `topics` | string[] | 是 |
| `description` | string \| null | 是 |
