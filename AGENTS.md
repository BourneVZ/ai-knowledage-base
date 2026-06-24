# AI 知识库助手 · AGENTS.md

## 项目概述

本项目是一个面向 AI/LLM/Agent 技术动态的自动化知识库助手：系统定时从 GitHub Trending 和 Hacker News 采集相关技术内容，经 AI Agent 分析、去重、摘要、打标签后，以结构化 JSON 形式沉淀到本地知识库，并支持通过 Telegram、飞书等渠道分发精选内容。

## 技术栈

- Python 3.12
- OpenCode + 国产大模型
- LangGraph
- OpenClaw

## 采集范围与过滤规则

- 数据来源：
  - GitHub Trending
  - Hacker News
- 仅保留与 AI、LLM、Agent 明确相关的内容。
- GitHub 仓库优先参考 topics、README、description、stars 增长、项目活跃度等信息判断。
- Hacker News 内容优先参考标题、正文链接、评论语境和来源站点判断。
- 与 AI/LLM/Agent 无直接关系的内容必须丢弃，不得为了凑数保留。
- 无法确认相关性的内容标记为 `needs_review`，不得直接发布。

## 编码规范

- 遵循 PEP 8。
- 变量、函数、模块、文件名使用 `snake_case`。
- 类名使用 `PascalCase`。
- 常量使用 `UPPER_SNAKE_CASE`。
- 公共函数、类、Agent 节点必须编写 Google 风格 docstring。
- 禁止裸 `print()`：
  - 运行时日志必须使用 `logging`。
  - CLI 输出必须通过统一的 console/output 封装。
- 网络请求必须设置超时、重试和明确的错误处理。
- 外部数据入库前必须做字段校验、去重和来源记录。
- 不在业务代码中硬编码 token、cookie、API key、webhook 地址等敏感信息。

## 项目结构

```text
.
├── .opencode/
│   ├── agents/          # Agent 角色定义、工作流节点、角色提示词
│   └── skills/          # 可复用技能：采集、解析、摘要、分类、分发等
├── knowledge/
│   ├── raw/             # 原始采集数据，按来源和日期归档
│   └── articles/        # AI 分析后的结构化知识条目 JSON
├── src/                 # Python 源码
├── tests/               # 单元测试和集成测试
└── AGENTS.md            # Agent 协作规则与项目约束
```

## 知识条目 JSON 格式

每条知识条目必须存储为独立 JSON 对象。字段应稳定、可追踪、便于后续检索和分发。

```json
{
  "id": "github-owner-repo-2026-06-24",
  "title": "Repository or Article Title",
  "source": "github_trending",
  "source_url": "https://github.com/owner/repo",
  "description": "Original source description.",
  "summary": "AI-generated concise summary.",
  "tags": ["ai", "llm", "agent"],
  "category": "AI Agent",
  "status": "draft",
  "language": "Python",
  "stars": 12345,
  "authors": ["owner"],
  "collected_at": "2026-06-24T10:30:00+08:00",
  "analyzed_at": "2026-06-24T10:45:00+08:00",
  "published_at": null,
  "innovation_score": 4,
  "difficulty_score": 3,
  "key_points": [
    "核心亮点 1",
    "核心亮点 2"
  ],
  "risks": [
    "潜在限制或不确定性"
  ],
  "raw_path": "knowledge/raw/github_trending/2026-06-24/owner_repo.json",
  "metadata": {
    "license": "MIT",
    "topics": ["ai", "agents", "llm"],
    "hn_points": null,
    "hn_comments": null
  }
}
```

### 字段要求

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | 全局唯一 ID，建议由来源、标题或仓库名、日期生成 |
| `title` | 是 | 仓库名、文章标题或 HN 标题 |
| `source` | 是 | 数据来源，例如 `github_trending`、`hacker_news` |
| `source_url` | 是 | 原始内容 URL |
| `description` | 否 | 原始描述或摘要 |
| `summary` | 是 | AI 生成的结构化摘要 |
| `tags` | 是 | 标签数组，至少包含一个领域标签 |
| `category` | 是 | 技术类别，例如 LLM 框架、AI Agent、推理引擎、向量数据库、提示工程 |
| `status` | 是 | `draft`、`needs_review`、`approved`、`published`、`rejected` |
| `collected_at` | 是 | 采集时间，ISO 8601 格式 |
| `analyzed_at` | 否 | 分析完成时间，ISO 8601 格式 |
| `published_at` | 否 | 分发时间，未发布时为 `null` |
| `innovation_score` | 否 | 创新评分，1-5 |
| `difficulty_score` | 否 | 使用难度评分，1-5 |
| `raw_path` | 是 | 对应原始数据文件路径 |
| `metadata` | 否 | 来源相关扩展信息 |

## Agent 角色概览

| 角色 | 主要职责 | 输入 | 输出 |
| --- | --- | --- | --- |
| 采集 Agent | 从 GitHub Trending 和 Hacker News 抓取候选内容，过滤 AI/LLM/Agent 相关条目，保存原始数据 | 来源配置、日期、关键词规则 | `knowledge/raw/` 下的原始 JSON |
| 分析 Agent | 对候选内容进行摘要、分类、打标签、评分，识别创新点、使用难度和潜在风险 | 原始 JSON、网页内容、仓库元数据 | 结构化知识条目草稿 |
| 整理 Agent | 去重、校验 JSON schema、更新状态，并准备 Telegram/飞书分发内容 | 分析结果、历史知识库、分发规则 | `knowledge/articles/` 下的最终 JSON 和分发 payload |

## 红线

- 绝对禁止提交或写入任何真实 token、API key、cookie、session、webhook 地址等敏感信息。
- 绝对禁止在未确认来源可靠性的情况下执行远程脚本、仓库安装脚本或复制粘贴的命令。
- 绝对禁止将未经校验的外部内容直接发布到 Telegram、飞书或其他渠道。
- 绝对禁止伪造采集来源、stars、HN points、发布时间、作者等事实字段。
- 绝对禁止用 AI 猜测替代可验证事实；无法确认时必须标记 `needs_review`。
- 绝对禁止覆盖或删除 `knowledge/raw/` 中的原始采集记录，除非用户明确要求。
- 绝对禁止在异常时静默失败；必须记录错误来源、上下文和可重试信息。
- 绝对禁止让 Agent 自行扩大采集范围到隐私数据、付费墙内容或违反目标站点规则的内容。

## 验收标准

- 能按日期从 GitHub Trending 和 Hacker News 生成原始采集文件。
- 能过滤出 AI/LLM/Agent 相关内容，并丢弃无关内容。
- 能为每条有效内容生成符合 JSON 格式要求的知识条目。
- 能通过 schema 校验、去重校验和状态流转校验。
- 能生成 Telegram/飞书可发送的分发 payload，但发布前必须经过 `approved` 状态检查。

## 验证方式

- 运行单元测试，覆盖采集、过滤、分析、schema 校验、去重、分发 payload 生成。
- 使用固定样例数据做集成测试，确保输出 JSON 字段完整且状态正确。
- 对外部请求使用 mock 或录制样例，避免测试依赖实时网络波动。
- 人工抽查每日样本，确认摘要没有编造事实，标签和评分理由可解释。
