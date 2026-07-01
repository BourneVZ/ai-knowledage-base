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

#### 2.3 创新与难度评分（1-5）

按以下两个维度分别评分，每个维度必须附一句评分理由：

**创新评分 `innovation_score`（1-5）**：

| 分数 | 含义       | 判断标准                                                 |
| ---- | ---------- | -------------------------------------------------------- |
| 5    | 改变格局   | 突破性新技术、范式转变、可能重塑领域发展方向的里程碑项目 |
| 4    | 显著创新   | 解决明确痛点的新颖方案，有明显差异化优势                 |
| 3    | 有创新     | 有趣的技术尝试、对现有方案的改进                         |
| 2    | 增量改进   | 工程化完善，但核心思路无太多新意                         |
| 1    | 同质化     | 与现有项目高度雷同，无实质创新                           |

**评分约束**：15 个项目中 innovation_score=5 的不超过 2 个。若候选超过 2 个，只保留最有价值的 2 个为 5 分，其余降至 4 分。

**难度评分 `difficulty_score`（1-5）**：

| 分数 | 含义       | 判断标准                                                 |
| ---- | ---------- | -------------------------------------------------------- |
| 5    | 极高       | 需深厚学术/工程背景，涉及底层系统、编译器等核心领域       |
| 4    | 较高       | 需要较强的领域知识，有一定学习曲线                       |
| 3    | 中等       | 有一定技术门槛，但文档完善、社区活跃                     |
| 2    | 较低       | 上手容易，适合快速集成                                   |
| 1    | 极低       | 即插即用，无需技术背景                                   |

#### 2.4 标签建议

为每条内容建议 3-5 个标签，标签词优先从以下归类中选取：

- **技术领域**：`llm`, `agent`, `rag`, `vector-db`, `prompt-engineering`, `inference`, `fine-tuning`, `embeddings`, `multimodal`, `tool-calling`, `agent-framework`
- **应用场景**：`code-generation`, `knowledge-base`, `chatbot`, `workflow`, `data-analysis`, `search`, `automation`, `content-generation`
- **特色标签**：`open-source`, `high-performance`, `lightweight`, `beginner-friendly`, `enterprise-ready`

禁止使用无信息量的标签如 `ai`, `ml`, `tool`（过于泛化）。

#### 2.5 技术分类

为每条内容指定一个 `category`，从以下归类中选取：

- `LLM 框架`、`AI Agent`、`推理引擎`、`向量数据库`、`提示工程`
- `RAG 系统`、`训练调优`、`多模态`、`工具调用`、`代码生成`
- `工作流编排`、`评测基准`、`部署推理`

### 3. 趋势发现

综合分析所有条目，识别共性趋势：

- **共同主题**：本轮分析中反复出现的技术方向或架构思想（如 "本地优先部署"、"多 Agent 协作"、"小模型崛起"），列出 2-4 个主题
- **新概念/术语**：本轮首次出现的值得关注的技术概念（如 `Mixture of Experts`、`Speculative Decoding`），如有则列出，无则为空
- 趋势描述必须基于本轮实际数据，不得凭空推断宏观行业趋势

### 4. 输出分析结果

将分析结果以 JSON 格式输出到 stdout，格式见下方「输出格式」章节。不写入文件（由整理 Agent 负责落地）。

## 注意事项

- 所有分析基于原始数据中的可验证事实，不可用 AI 猜测替代
- 评分理由必须具体（引述具体功能或架构设计），不得使用 "看起来不错"、"应该有用" 等模糊理由
- 摘要必须在 50 字以内，使用中文，`Read` 后逐条数过再写入
- 若原始文件中的 `items` 不足 15 条，以实际数量为准，评分分布比例不变
- 无法获取足够信息做深度分析的项目，标记 `status: "needs_review"`，不纳入趋势发现
- 所有日志记录到 `logging.getLogger(__name__)`

## 输出格式

输出到 stdout，格式如下：

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
      "title": "Repository or Article Title",
      "url": "https://github.com/owner/repo",
      "summary": "核心技术点，一句话，≤50字，使用中文。",
      "highlights": [
        "技术亮点 1 —— 依据来源",
        "技术亮点 2 —— 依据来源"
      ],
      "innovation_score": 4,
      "innovation_score_reason": "具体理由，说明创新程度判断依据。",
      "difficulty_score": 3,
      "difficulty_score_reason": "具体理由，说明难度判断依据。",
      "suggested_tags": ["agent-framework", "workflow", "open-source"],
      "category": "AI Agent",
      "status": "draft"
    }
  ]
}
```

### 字段说明

| 字段                              | 类型    | 必填 | 说明                                                |
| --------------------------------- | ------- | ---- | --------------------------------------------------- |
| `source`                          | string  | 是   | 固定值 `tech-summary`                              |
| `skill`                           | string  | 是   | 固定值 `tech-summary`                              |
| `analyzed_at`                     | string  | 是   | ISO 8601 格式分析完成时间（含时区）                 |
| `input_files`                     | array   | 是   | 本次分析使用的原始采集文件路径列表                  |
| `trends`                          | object  | 是   | 趋势发现结果                                        |
| `trends.common_themes`            | array   | 是   | 共同主题列表，2-4 个                                |
| `trends.new_concepts`             | array   | 是   | 新概念列表，可为空数组                              |
| `items`                           | array   | 是   | 分析结果列表                                        |
| `items[].title`                   | string  | 是   | 仓库名或文章标题                                    |
| `items[].url`                     | string  | 是   | 原始链接                                            |
| `items[].summary`                 | string  | 是   | 精简摘要，≤50 字，使用中文                          |
| `items[].highlights`              | array   | 是   | 技术亮点，2-3 个，每条附带依据来源                  |
| `items[].innovation_score`        | integer | 是   | 创新评分 1-5                                        |
| `items[].innovation_score_reason` | string  | 是   | 创新评分理由                                        |
| `items[].difficulty_score`        | integer | 是   | 使用难度评分 1-5                                    |
| `items[].difficulty_score_reason` | string  | 是   | 难度评分理由                                        |
| `items[].suggested_tags`          | array   | 是   | 建议标签 3-5 个                                     |
| `items[].category`                | string  | 是   | 技术类别，如 `AI Agent`、`LLM 框架` 等              |
| `items[].status`                  | string  | 是   | `draft` 或 `needs_review`                         |
