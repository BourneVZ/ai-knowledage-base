"""LangGraph 状态定义 — AI 知识库工作流的核心数据结构。

所有节点共享同一个 :class:`KBState`，通过 ``TypedDict`` 保证类型安全。
每个节点只修改自己负责的字段，实现职责隔离。

数据流向（V3 完整 · 7 节点）::

    plan → sources → analyses → review ─[通过]→ organize → END
                                    ├─[未通过]→ revise → review（循环）
                                    └─[超限]──→ human_flag → END

``review`` 三路条件边是本项目的核心教学点——质量门控 + 定向修改循环 + 人工介入兜底。
"""

from __future__ import annotations

from typing import Any, TypedDict


class KBState(TypedDict):
    """知识库工作流的全局状态。

    遵循「报告式通信」原则：各字段存放结构化摘要而非原始数据，
    原始采集记录只落在 ``knowledge/raw/``，状态中仅保留可序列化的轻量结果。

    Fields:
        plan: Planner 输出的策略（下游据此调整采集量、阈值与循环上限）。
        sources: 采集阶段产出的原始候选数据（已过滤、去重后的轻量摘要，
            不含原始 HTML/API 全量响应）。
        analyses: LLM 分析后的结构化结果（每条含 summary、tags、score）。
        articles: 格式化、去重后的最终知识条目。
        review_feedback: 审核 Agent 的反馈意见（中文）。
        review_passed: 审核是否通过。
        needs_human_review: 是否需人工介入（审核超限时置 True）。
        iteration: 当前审核循环次数（最多 3 次）。
        cost_tracker: Token 用量追踪。
    """

    plan: dict[str, Any]
    # 规划结果 — Planner 输出的策略 dict，包含 strategy/github_limit/
    # min_innovation_score/max_iterations/rationale，被下游节点共同消费。

    sources: list[dict[str, Any]]
    # 采集结果 — 报告式摘要：仅含 title/source/source_url/description 等
    # 关键字段，不携带原始 HTML 或 API 完整响应。

    analyses: list[dict[str, Any]]
    # 分析结果 — 每条为 LLM 输出的结构化字典，至少包含
    # summary（摘要）、tags（标签）、category（分类）、
    # innovation_score / difficulty_score（评分）。

    articles: list[dict[str, Any]]
    # 知识条目 — 经过去重、schema 校验、状态流转后的最终格式，
    # 字段契约与 AGENTS.md 中「知识条目 JSON 格式」一致。

    review_feedback: str
    # 审核反馈 — 具体改进建议（中文）；非空字符串表示需要修改后重新审核。

    review_passed: bool
    # 审核是否通过 — 作为条件边（review → save 或 review → analyze）的判断依据。

    needs_human_review: bool
    # 是否需人工介入 — 审核循环超过上限仍未通过时由 HumanFlag 节点置 True。

    iteration: int
    # 审核迭代次数 — 从 0 开始，达到上限后转人工介入（不再强制通过）。

    cost_tracker: dict[str, Any]
    # Token 用量追踪 — 累加统计，约定 key：
    # {"prompt_tokens": int, "completion_tokens": int, "total_cost_yuan": float}


FACTUAL_FIELDS: tuple[str, ...] = (
    "source",
    "title",
    "url",
    "description",
    "stars",
    "collected_at",
    "raw_path",
)
"""分析条目中由采集阶段确定、LLM 不得篡改的事实字段。

analyzer/reviser 在合并 LLM 输出时必须用原始值回填这些字段，防止模型伪造
``collected_at``、``stars`` 等事实数据。
"""


def restore_factual_fields(
    merged: dict[str, Any], factual: dict[str, Any]
) -> dict[str, Any]:
    """用采集阶段的原始值回填事实字段，禁止 LLM 篡改。

    Args:
        merged: LLM 输出或已合并的字典（原地修改）。
        factual: 采集阶段的事实字典（含 ``title``/``url``/``stars``/
            ``collected_at`` 等）。

    Returns:
        回填事实字段后的同一字典（便于链式使用）。
    """
    for field in FACTUAL_FIELDS:
        if field in factual:
            merged[field] = factual[field]
    return merged
