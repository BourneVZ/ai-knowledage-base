# skill: github-trending · 需求

## 要做什么
- 调 GitHub Search API：`created:>{7天前}` + `stars:>100`，sort by stars，per_page=30
- 综合过滤：纳入 AI/ML/LLM/Agent 相关、开发者工具、框架重大更新；排除 Awesome 列表、纯教程、Star 刷量、无 README
- skill 内按 `full_name` 去重
- 按 stars 降序取 Top 15
- 输出 JSON 数组 · 字段 [name, full_name, url, stars, language, topics, description]
- 写入文件 `knowledge/raw/github-trending-{YYYY-MM-DD}.json`

## 不做什么
- 不生成中文摘要（摘要由分析 Agent 负责）
- 不处理 Hacker News（由 collector Agent 聚合）

## 边界 & 验收
- 未经认证 API 限频 10 次/分钟
- 失败时返回空数组 · 不抛异常
- 输出必须通过 jsonschema 验证

## 怎么验证
- 跑 `skill-invoke github-trending` 后 · 检查输出文件是 JSON 且字段完整
