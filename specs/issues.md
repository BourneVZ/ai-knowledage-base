# Issues · AI 知识库三 Agent

来源：`specs/agents-prd.md`

---

## Issue 1: Infra — 项目脚手架 + CI 基线

## What to build

搭建 AI 知识库项目的基础设施：Python 3.12 项目骨架、依赖管理、日志体系、环境变量注入、CI 验证管线。跑通一条空流水线骨架，确保后续 Agent 开发有稳定的工程基础。

## Acceptance criteria

- [ ] `pyproject.toml` 定义项目元数据与直接依赖（Black、ruff、mypy、pytest、pytest-cov、tenacity、LangGraph）
- [ ] `src/` 目录结构就绪，含 logging 封装（禁止裸 `print()`）
- [ ] `.env` 模板文件（不入库），敏感配置仅通过环境变量注入
- [ ] CI（GitHub Actions）执行：ruff check → ruff format --check → mypy --strict src/ → pytest --cov --cov-branch --cov-fail-under=80
- [ ] 禁止未关联 Issue 的 TODO 检查通过
- [ ] `AGENTS.md` 项目约束文件完整

## Blocked by

None - can start immediately

---

## Issue 2: Pipeline — 采集→分析→整理 全链路

## What to build

实现 collector → analyzer → organizer 三 Agent 串行流水线。Collector 抓取 GitHub Trending 并过滤 AI 相关条目存入 `knowledge/raw/`；Analyzer 读取 raw 数据给出摘要、评分、标签；Organizer 去重校验后写入 `knowledge/articles/`。LangGraph 编排串行执行，上游失败时终止下游，所有网络请求含重试（tenacity 指数退避 3 次）。

## Acceptance criteria

- [ ] Collector：从 GitHub Trending 抓取 Top 50，按 AI/LLM/Agent 关键词过滤，存入 `knowledge/raw/github-trending-{date}.json`
- [ ] Collector：网络请求设超时 30s，实现 tenacity 重试
- [ ] Analyzer：读取 raw 数据，对每条给出中文摘要、1-10 评分及理由、2-4 个亮点、建议标签
- [ ] Analyzer：无法确认的信息标记 `needs_review`
- [ ] Organizer：按 id/url 去重，按 `{date}-{source}-{slug}.json` 写入 articles/，schema 校验通过
- [ ] Organizer：不覆盖 `knowledge/raw/` 原始数据
- [ ] LangGraph 串行编排，上游 Agent 异常时下游不执行
- [ ] 数据传递契约：Collector→Analyzer 通过 raw JSON 文件，Analyzer→Organizer 通过分析结果 JSON
- [ ] 全链路单测覆盖率 ≥ 80%（外部请求 mock）

## Blocked by

- Issue #1 (Infra: 项目脚手架 + CI 基线)

---

## Issue 3: Scheduler — 每日 UTC 0:00 定时触发 + 幂等

## What to build

通过 GitHub Actions cron 实现每日 UTC 0:00 自动触发全链路流水线。确保幂等执行（同一天多次触发不会重复写入），运行日志落盘。

## Acceptance criteria

- [ ] GitHub Actions workflow 配置 cron: `0 0 * * *`（UTC 0:00）
- [ ] 执行前检查当天是否已有产出，若存在则跳过（幂等）
- [ ] 运行日志写入 `knowledge/logs/` 或通过 logging 输出到 CI log
- [ ] 支持手动触发（workflow_dispatch）
- [ ] 流水线失败时 CI 标记 failed，输出错误摘要

## Blocked by

- Issue #2 (Pipeline: 采集→分析→整理 全链路)

---

## Issue 4: Observability — 运行历史 + 进度追踪

## What to build

为三 Agent 流水线增加可观测性：各 Agent 阶段进度上报、每次运行摘要记录、失败告警（至少日志级别 ERROR 输出关键上下文）。

## Acceptance criteria

- [ ] 每个 Agent 执行前后日志记录：开始时间、结束时间、条目数、失败原因
- [ ] 每次流水线运行生成摘要：采集数、分析数、整理数、跳过/失败数
- [ ] 异常时记录：来源 URL、状态码、重试次数、异常类型（禁止静默失败）
- [ ] 摘要数据以结构化格式落盘，便于后续检索和展示
- [ ] CI 日志中 pipeline 失败时可见错误阶段和原因

## Blocked by

- Issue #2 (Pipeline: 采集→分析→整理 全链路)
