# AI 知识库 · 项目愿景 v1.1

## 要做什么
- 每天从 GitHub Trending 和 Hacker News 抓取候选内容
  - GitHub Trending：Top 10，按 Topic 过滤（含 `ai` / `llm` / `agent`），同时参考 README、description、stars 增长、项目活跃度判断相关性
  - Hacker News：按标题、正文链接、评论语境、来源站点判断 AI/LLM/Agent 相关性
- 丢弃与 AI/LLM/Agent 无直接关系的内容；无法确认相关性的标记 `needs_review`
- 用 Agent 分析每个通过过滤的条目：
  - 技术类别（分类 + 文字说明）
  - 创新点（文字说明 + 1-5 打分）
  - 使用难度（文字说明 + 1-5 打分）
  - 代码结构（项目目录/模块组织概览，仅 GitHub 条目）
  - 综合摘要（AI 生成的简明摘要）
  - 关键亮点（核心创新点列表）
  - 潜在风险（限制或不确定性列表）
- 输出结构化 JSON 知识条目，支持通过 Telegram、飞书等渠道分发
- 发布前必须经过状态流转：`draft` → `needs_review` / `approved` → `published` / `rejected`

## 知识条目 JSON 格式

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
  "innovation_notes": "相比同类方案的核心新意",
  "difficulty_score": 3,
  "difficulty_notes": "上手门槛描述（依赖、硬件、学习曲线）",
  "code_structure": {
    "tree": "目录树",
    "modules": "各目录/模块职责说明"
  },
  "key_points": ["核心亮点 1", "核心亮点 2"],
  "risks": ["潜在限制或不确定性"],
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
| `id` | 是 | 全局唯一 ID，由来源、标题或仓库名、日期生成 |
| `title` | 是 | 仓库名、文章标题或 HN 标题 |
| `source` | 是 | `github_trending` 或 `hacker_news` |
| `source_url` | 是 | 原始内容 URL |
| `description` | 否 | 原始描述或摘要 |
| `summary` | 是 | AI 生成的结构化摘要 |
| `tags` | 是 | 标签数组，至少包含一个领域标签 |
| `category` | 是 | 技术类别，如 LLM 框架、AI Agent、推理引擎、向量数据库、提示工程 |
| `status` | 是 | `draft` / `needs_review` / `approved` / `published` / `rejected` |
| `collected_at` | 是 | 采集时间，ISO 8601 |
| `analyzed_at` | 否 | 分析完成时间，ISO 8601 |
| `published_at` | 否 | 分发时间，未发布时为 `null` |
| `innovation_score` | 是 | 创新评分，1-5 |
| `innovation_notes` | 是 | 创新点文字说明 |
| `difficulty_score` | 是 | 使用难度评分，1-5 |
| `difficulty_notes` | 是 | 使用难度文字说明 |
| `code_structure` | 否 | 代码结构（目录树 + 模块说明），仅 GitHub 条目 |
| `key_points` | 否 | 核心亮点列表 |
| `risks` | 否 | 潜在限制或不确定性 |
| `raw_path` | 是 | 对应原始数据文件路径 |
| `metadata` | 否 | 来源相关扩展信息 |

## 状态流转

```
draft → needs_review → approved → published
  ↓                      ↓
rejected              rejected
```

## Agent 角色

| 角色 | 职责 | 输入 | 输出 |
| --- | --- | --- | --- |
| 采集 Agent | 从 GitHub Trending 和 HN 抓取候选内容，过滤 AI/LLM/Agent 相关条目，保存原始数据 | 来源配置、日期、关键词规则 | `knowledge/raw/` 下的原始 JSON |
| 分析 Agent | 对候选内容进行摘要、分类、打标签、评分，识别创新点、使用难度和潜在风险 | 原始 JSON、网页内容、仓库元数据 | 结构化知识条目草稿 |
| 整理 Agent | 去重、校验 JSON schema、更新状态，准备 Telegram/飞书分发内容 | 分析结果、历史知识库、分发规则 | `knowledge/articles/` 下的最终 JSON 和分发 payload |

## 不做什么
- 不采集与 AI/LLM/Agent 无关的内容
- 不伪造采集来源、stars、HN points、发布时间、作者等事实字段
- 不用 AI 猜测替代可验证事实
- 不覆盖或删除 `knowledge/raw/` 中的原始采集记录
- 不在异常时静默失败
- 不自行扩大采集范围到隐私数据、付费墙内容或违反目标站点规则的内容

## 红线（绝对禁止）
- 提交或写入真实 token、API key、cookie、session、webhook 地址等敏感信息
- 未经确认来源可靠性即执行远程脚本、仓库安装脚本或复制粘贴的命令
- 将未经校验的外部内容直接发布到 Telegram、飞书或其他渠道

## 验收标准
- 能按日期从 GitHub Trending 和 HN 生成原始采集文件
- 能过滤出 AI/LLM/Agent 相关内容，丢弃无关内容
- 能为每条有效内容生成符合 JSON schema 的知识条目
- 能通过 schema 校验、去重校验和状态流转校验
- 能生成 Telegram/飞书可发送的分发 payload，发布前必须经过 `approved` 状态检查

## 怎么验证
- 单元测试覆盖：采集、过滤、分析、schema 校验、去重、分发 payload 生成
- 固定样例数据集成测试，确保输出 JSON 字段完整且状态正确
- 外部请求使用 mock 或录制样例，避免依赖实时网络
- 人工抽查每日样本，确认摘要无编造事实，标签和评分理由可解释
