---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能
allowed-tools: Read, Grep, Glob, WebFetch
---

# GitHub Trending 采集技能

## 使用场景

当用户需要从 GitHub Trending 页面采集热门 AI/LLM/Agent 相关开源项目时使用此技能。适用于每日知识库采集、技术趋势追踪、竞品分析等场景。

## 执行步骤

### 1. 搜索热门仓库

通过 GitHub API 获取当前 Trending 仓库列表：

- 获取 GitHub Trending 页面：`https://github.com/trending?since=daily`
- 备用方案：使用 GitHub Search API 按 stars 降序搜索近期创建的项目，过滤参数 `q=created:>YYYY-MM-DD` 配合 `sort=stars&order=desc`
- 使用 `WebFetch` 工具获取页面内容，解析出仓库名称、描述、语言、stars 等字段

### 2. 提取信息

从 API 响应或页面内容中提取每个仓库的关键字段：

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `name` | full_name / 页面标题 | `owner/repo` 格式 |
| `url` | html_url | 仓库主页链接 |
| `description` | description | 项目描述 |
| `stars` | stargazers_count | 星标数 |
| `language` | language | 主要编程语言 |
| `topics` | topics | 仓库标签 |

### 3. 过滤

仅保留与 AI/LLM/Agent 明确相关的项目，过滤规则：

- **纳入**：项目涉及 LLM、AI Agent、RAG、向量数据库、提示工程、推理引擎、模型训练/推理/部署、多模态 AI、AI 框架
- **纳入**：topics 或 description 中包含关键词 `ai`, `llm`, `agent`, `machine-learning`, `deep-learning`, `nlp`, `gpt`, `transformer`, `rag`, `vector`, `embedding`, `prompt`, `inference`, `fine-tuning`
- **排除**：Awesome 列表类项目（`awesome-*`）、非直接相关的通用工具、纯前端 UI 库、非 AI 领域的 devops/运维工具
- 无法确认相关性的标记为 `needs_review`，不可直接纳入最终输出

### 4. 去重

- 以 `name`（`owner/repo`）为唯一键去重
- 若同一天多次采集，保留最新数据覆盖旧数据
- 与历史 `knowledge/raw/github-trending-*.json` 文件对比，标记首次出现的新项目

### 5. 撰写中文摘要

为每个通过过滤的项目撰写中文摘要，遵循以下公式：

> **项目名** + **做什么** + **为什么值得关注**

要求：

- 一句话概括，控制在 50-120 字
- 突出 AI/LLM/Agent 领域的技术亮点和创新点
- 避免主观评价，基于项目文档和 README 中的客观事实
- 不可编造功能或声称未经证实的性能数据

### 6. 排序取 Top 15

- 按 `stars` 降序排序
- 新兴项目（最近 7 天内创建且 stars 增长快）适当加权至多提升 3 位
- 取前 15 个项目作为最终输出
- 若过滤后不足 15 个，以实际数量为准

### 7. 输出 JSON

将结果写入 `knowledge/raw/github-trending-YYYY-MM-DD.json`，格式见下方「输出格式」章节。

## 注意事项

- 网络请求必须设置超时（connect 10s, read 30s），失败时重试最多 3 次（指数退避）
- 不得伪造或猜测 stars、描述、topics 等事实字段；无法获取的信息留空或标记 `needs_review`
- 不得为了凑数保留与 AI/LLM/Agent 无关的项目
- 输出 JSON 必须通过 pydantic schema 校验
- 禁止覆盖已有的同日原始采集文件，如需更新使用 `--force` 显式声明
- 所有采集日志记录到 `logging.getLogger(__name__)`

## 输出格式

输出文件路径：`knowledge/raw/github-trending-YYYY-MM-DD.json`

```json
{
  "source": "github_trending",
  "skill": "github-trending",
  "collected_at": "2026-06-25T10:30:00+08:00",
  "items": [
    {
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "summary": "项目名 + 做什么 + 为什么值得关注的中文摘要",
      "stars": 12345,
      "language": "Python",
      "topics": ["ai", "llm", "agent"]
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `source` | string | 是 | 固定值 `github_trending` |
| `skill` | string | 是 | 固定值 `github-trending` |
| `collected_at` | string | 是 | ISO 8601 格式采集时间（含时区） |
| `items` | array | 是 | 过滤排序后的 Top 15 项目列表 |
| `items[].name` | string | 是 | `owner/repo` 格式 |
| `items[].url` | string | 是 | GitHub 仓库完整 URL |
| `items[].summary` | string | 是 | 中文摘要，50-120 字 |
| `items[].stars` | integer | 是 | 星标数 |
| `items[].language` | string \| null | 否 | 主要编程语言，无法确定时为 null |
| `items[].topics` | array[string] | 否 | 仓库 topics 标签列表 |
