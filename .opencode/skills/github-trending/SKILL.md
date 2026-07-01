---
name: github-trending
description: 当需要抓取 GitHub Trending 热门项目、查看 GitHub 今天什么火、发现 AI/LLM/Agent 新项目、或过滤 trending 中的 AI 相关仓库时使用
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# GitHub 热门项目采集技能

## 使用场景

在知识库采集阶段，通过 GitHub Search API 搜索并采集 AI 领域热门开源项目。

## 步骤

### 1. 搜索热门仓库

使用 `WebFetch` 调用 GitHub Search API：

```
GET https://api.github.com/search/repositories?q=created:>{7天前日期}+stars:>100&sort=stars&order=desc&per_page=30
```

- `{7天前日期}` 格式为 `YYYY-MM-DD`，按当天日期向前推算 7 天。
- 未经认证的 API 限频为 **10 次/分钟**，若返回 403 或 rate limit 错误则等待后重试。

**完成条件**：获取到 API 响应，`items` 数组非空。

### 2. 提取仓库信息

从 API 响应 `items` 数组中逐条提取以下字段：

| 字段 | API 字段 | 说明 |
|------|----------|------|
| `name` | `full_name` | 仓库全名（`owner/repo`） |
| `full_name` | `full_name` | 仓库全名，用于去重 |
| `url` | `html_url` | 仓库公开链接 |
| `stars` | `stargazers_count` | 星标数，整数 |
| `language` | `language` | 主要编程语言 |
| `topics` | `topics` | 主题标签数组 |
| `description` | `description` | 项目描述 |

缺失字段 → `null`。

**完成条件**：每条记录的上述 7 个字段均已提取。

### 3. 过滤

**纳入**：
- AI / ML / LLM / Agent 明确相关的项目
- AI 领域开发者工具、框架重大更新
- 具备工程价值或生态影响力的项目

**排除**：
- Awesome 列表、资源合集类仓库
- 纯教程、示例代码、课程笔记
- Star 刷量嫌疑（如 1 天内暴涨但无实质内容）
- 无 README 的仓库

**完成条件**：保留的仓库均符合纳入标准，排除的仓库均命中排除规则。

### 4. 去重

按 `full_name` 去重，同一仓库只保留一条记录。

**完成条件**：`full_name` 无重复。

### 5. 排序取 Top 15

按 `stars` 降序排列，取前 15 条。

**完成条件**：结果数组长度 ≤ 15，按 stars 从高到低排列。

### 6. 写入文件

将 JSON 数组写入以下路径：

```
knowledge/raw/github-trending-{YYYY-MM-DD}.json
```

- `{YYYY-MM-DD}` 为当日日期。
- 使用 `Write` 工具写入文件。
- 文件内容为合法 JSON 数组，可被标准 JSON 解析器解析。

**完成条件**：文件已写入，内容为合法 JSON，数组长度 ≤ 15。

## 约束

- 使用 GitHub Search API，注意未经认证限频 **10 次/分钟**。
- **禁止**编造不存在的仓库、stars 数、topics 或项目能力。
- 失败（API 调用失败、解析异常）→ 输出 `[]`，永不抛异常。

## 输出格式

```json
[
  {
    "name": "owner/repo",
    "full_name": "owner/repo",
    "url": "https://github.com/owner/repo",
    "stars": 12345,
    "language": "Python",
    "topics": ["ai", "llm"],
    "description": "项目简述"
  }
]
```

| 字段 | 类型 | 必填 |
|------|------|------|
| `name` | string | 是 |
| `full_name` | string | 是 |
| `url` | string | 是 |
| `stars` | integer | 是 |
| `language` | string \| null | 是 |
| `topics` | string[] | 是 |
| `description` | string \| null | 是 |
