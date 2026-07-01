# AI 知识库 · 三 Agent PRD v0.2

## 总流程
每天 UTC 0:00 触发 · collector → analyzer → organizer · 串行。

## Agent 职责
- collector: 调 GitHub Search API + 抓 Hacker News · 综合过滤 AI 相关 · 去重 · Top 15 · 写入 knowledge/raw/
- analyzer: 读 raw · 逐条中文摘要（≤50字）+ 高亮提取 · 二维评分（innovation 1-5 + difficulty 1-5）· 标签 3-5 个 + category 分类 · 趋势发现 · 输出包装对象到 stdout
- organizer: 读分析结果 · 去重 · schema 校验 · 整理为 knowledge/articles/ 下的标准 JSON

## 开放问题（? 用 to-issues 细化成任务）
- 上游失败下游怎么办？
- 数据怎么传？文件 or 消息？
- 重跑策略？
- 进度追踪？
