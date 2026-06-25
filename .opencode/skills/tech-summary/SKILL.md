---
name: tech-summary
description: 当需要对采集的技术内容进行深度分析总结时使用此技能
allowed-tools: Read, Grep, Glob, WebFetch
---

# 技术深度分析总结技能

## 使用场景

当用户需要对 `knowledge/raw/` 目录下已采集的技术内容（如 GitHub Trending、Hacker News）进行深度分析、评分和趋势发现时使用此技能。适用于每日分析 Pipeline 中的第二步，将原始采集数据转化为结构化分析结果。

## 执行步骤

### 1. 读取最新采集文件

- 扫描 `knowledge/raw/` 目录，找到日期最新的采集文件：
  - `github-trending-YYYY-MM-DD.json`（GitHub Trending）
  - `hacker-news-YYYY-MM-DD.json`（Hacker News，如有）
- 使用 `Read` 工具加载文件内容，提取 `items` 数组
- 若同一天有多个来源，合并 `items` 统一分析

### 2. 逐条深度分析

对每条项目/文章进行以下维度的分析：

#### 2.1 精简摘要（≤50 字）

用一句话概括核心内容，比采集阶段的摘要更凝练：

> **核心技术点** + **解决什么问题**

- 必须在 50 字以内（含标点）
- 去除 marketing 话术，聚焦技术实质

#### 2.2 技术亮点（2-3 个）

从项目文档、README、技术博客中提取 2-3 个有事实支撑的技术亮点：

- 每个亮点一行，附带其依据来源（如 README 某功能、技术架构图中的设计、benchmark 数据）
- 禁止编造亮点；若无可靠信息来源，亮点字段留空
- 优先关注：架构创新、性能突破、易用性改进、生态整合、差异化能力

#### 2.3 关注度评分（1-10）

按以下标准评分，必须附一句评分理由：

| 分数 | 含义 | 判断标准 |
| --- | --- | --- |
| 9-10 | 改变格局 | 突破性新技术、范式转变、可能重塑领域发展方向的里程碑项目 |
| 7-8 | 直接有帮助 | 解决明确痛点、显著提效、可立即落地使用的高质量项目 |
| 5-6 | 值得了解 | 有趣的技术尝试、有潜力的早期项目、特定场景有价值 |
| 1-4 | 可略过 | 同质化严重、实际价值有限、尚不成熟的 demo 级项目 |

**评分约束**：15 个项目中 9-10 分不超过 2 个。若候选超过 2 个，只保留最有价值的 2 个为 9-10 分，其余降至 8 分。

#### 2.4 标签建议

为每条内容建议 3-5 个标签，标签词优先从以下归类中选取：

- **技术领域**：`llm`, `agent`, `rag`, `vector-db`, `prompt-engineering`, `inference`, `fine-tuning`, `embeddings`, `multimodal`, `tool-calling`, `agent-framework`
- **应用场景**：`code-generation`, `knowledge-base`, `chatbot`, `workflow`, `data-analysis`, `search`, `automation`, `content-generation`
- **特色标签**：`open-source`, `high-performance`, `lightweight`, `beginner-friendly`, `enterprise-ready`

禁止使用无信息量的标签如 `ai`, `ml`, `tool`（过于泛化）。

### 3. 趋势发现

综合分析所有条目，识别共性趋势：

- **共同主题**：本轮分析中反复出现的技术方向或架构思想（如 "本地优先部署"、"多 Agent 协作"、"小模型崛起"），列出 2-4 个主题
- **新概念/术语**：本轮首次出现的值得关注的技术概念（如 `Mixture of Experts`、`Speculative Decoding`），如有则列出，无则为空
- 趋势描述必须基于本轮实际数据，不得凭空推断宏观行业趋势

### 4. 输出分析结果 JSON

将分析结果写入 `knowledge/articles/analysis-YYYY-MM-DD.json`，格式见下方「输出格式」章节。

## 注意事项

- 所有分析基于原始数据中的可验证事实，不可用 AI 猜测替代
- 评分理由必须具体（引述具体功能或架构设计），不得使用 "看起来不错"、"应该有用" 等模糊理由
- 摘要必须在 50 字以内，`Read` 后逐条数过再写入
- 若原始文件中的 `items` 不足 15 条，以实际数量为准，评分分布比例不变
- 无法获取足够信息做深度分析的项目，标记 `analysis_status: "insufficient_data"`，不纳入趋势发现
- 所有日志记录到 `logging.getLogger(__name__)`

## 输出格式

输出文件路径：`knowledge/articles/analysis-YYYY-MM-DD.json`

```json
{
  "source": "tech-summary",
  "skill": "tech-summary",
  "analyzed_at": "2026-06-25T12:00:00+08:00",
  "input_files": [
    "knowledge/raw/github-trending-2026-06-25.json"
  ],
  "trends": {
    "common_themes": [
      "本地优先部署",
      "多 Agent 协作"
    ],
    "new_concepts": [
      "Speculative Decoding"
    ]
  },
  "items": [
    {
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "summary": "的核心技术点，一句话，50字以内。",
      "highlights": [
        "技术亮点 1 —— 依据来源",
        "技术亮点 2 —— 依据来源"
      ],
      "score": 8,
      "score_reason": "具体评分理由，引用项目特性说明",
      "suggested_tags": ["agent-framework", "workflow", "open-source"],
      "analysis_status": "completed"
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `source` | string | 是 | 固定值 `tech-summary` |
| `skill` | string | 是 | 固定值 `tech-summary` |
| `analyzed_at` | string | 是 | ISO 8601 格式分析完成时间（含时区） |
| `input_files` | array | 是 | 本次分析使用的原始采集文件路径列表 |
| `trends` | object | 是 | 趋势发现结果 |
| `trends.common_themes` | array | 是 | 共同主题列表，2-4 个 |
| `trends.new_concepts` | array | 是 | 新概念列表，可为空数组 |
| `items` | array | 是 | 分析结果列表 |
| `items[].name` | string | 是 | 项目/文章名称 |
| `items[].url` | string | 是 | 原始链接 |
| `items[].summary` | string | 是 | 精简摘要，≤50 字 |
| `items[].highlights` | array | 是 | 技术亮点，2-3 个，每条附带依据来源 |
| `items[].score` | integer | 是 | 关注度评分 1-10 |
| `items[].score_reason` | string | 是 | 评分理由 |
| `items[].suggested_tags` | array | 是 | 建议标签 3-5 个 |
| `items[].analysis_status` | string | 是 | `completed` 或 `insufficient_data` |
