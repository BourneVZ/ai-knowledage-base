"""Reviewer 节点 — 对分析结果进行 5 维度质量审核。

核心原则：只评估不修改（Evaluate, don't modify）。Reviewer 读取 Analyzer 产出的
``analyses``，不修改任何内容，仅输出加权总分、通过与否与反馈意见，供条件边决定
下一步走向（save 或回到 organize 修正）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from core.config import load_config
from core.llm import accumulate_usage, chat_json
from workflows.state import KBState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

REVIEWER_WEIGHTS: dict[str, float] = {
    "summary_quality": 0.25,
    "technical_depth": 0.25,
    "relevance": 0.20,
    "originality": 0.15,
    "formatting": 0.15,
}
"""5 个评分维度的权重（总和为 1.0），调整权重无需改动 prompt。"""

REVIEWER_PASS_THRESHOLD: float = 7.0
"""加权总分及格线兜底值（config.yaml 的 review.pass_threshold 可覆盖）。"""

REVIEWER_SYSTEM: str = "你是严格但公正的知识库质量审核员。给出具体、可操作的反馈。"
"""审核系统提示词。"""

REVIEWER_TEMPERATURE: float = 0.1
"""审核采样温度，低温度保证评分一致性。"""

REVIEW_SAMPLE_SIZE: int = 5
"""每次只审核前 N 条 analyses，控制 token 消耗。"""

DEFAULT_MAX_ITERATIONS: int = 3
"""plan 未指定 max_iterations 时的内部兜底上限。"""


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _weighted_score(scores: object) -> float:
    """按权重重算加权总分，不信任模型的算术结果。

    Args:
        scores: LLM 返回的 ``scores`` 字段（应为 ``{维度名: 1-10 分}`` 的字典）。

    Returns:
        加权总分（保留两位小数），缺失或类型非法时返回 0.0。
    """
    if not isinstance(scores, dict):
        return 0.0

    total = 0.0
    for dim, weight in REVIEWER_WEIGHTS.items():
        raw = scores.get(dim, 0)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            total += float(raw) * weight
    return round(total, 2)


# ---------------------------------------------------------------------------
# 节点定义
# ---------------------------------------------------------------------------


def review_node(state: KBState) -> dict[str, Any]:
    """Reviewer 节点：对 ``analyses`` 进行 5 维度质量审核。

    审核对象是 :data:`state["analyses"]`（而非 ``articles``，后者在 organize 之后
    才存在）。只评估不修改，加权总分由代码重算（不信任模型算术），低于
    :data:`REVIEWER_PASS_THRESHOLD` 时返回 ``review_passed=False``。

    Args:
        state: 工作流共享状态。

    Returns:
        部分状态更新，包含 ``review_passed``、``review_feedback``、
        递增后的 ``iteration`` 和累加后的 ``cost_tracker``。
    """
    logger.info("[Reviewer] 开始第 %d 次审核", state["iteration"] + 1)
    analyses = state["analyses"]
    iteration = state["iteration"]
    tracker = state["cost_tracker"]

    if not analyses:
        logger.info("[Reviewer] 没有条目需要审核，直接通过")
        return {
            "review_passed": True,
            "review_feedback": "没有条目需要审核",
            "iteration": iteration + 1,
        }

    plan = state.get("plan") or {}
    max_iterations = int(plan.get("max_iterations", DEFAULT_MAX_ITERATIONS))
    cfg = load_config()
    pass_threshold = float(
        cfg.get("review", {}).get("pass_threshold", REVIEWER_PASS_THRESHOLD)
    )

    if iteration >= max_iterations:
        logger.warning("[Reviewer] 已达审核上限 %d 次，内部兜底通过", max_iterations)
        return {
            "review_passed": True,
            "review_feedback": "已达审核上限，内部兜底通过",
            "iteration": iteration + 1,
        }

    sample = analyses[:REVIEW_SAMPLE_SIZE]

    prompt = f"""你是知识库质量审核员。请审核以下分析结果：

{json.dumps(sample, ensure_ascii=False, indent=2)}

请按以下维度评分（每项 1-10 分）：
1. summary_quality  - 摘要质量
2. technical_depth  - 技术深度
3. relevance        - 相关性
4. originality      - 原创性
5. formatting       - 格式规范

请用 JSON 格式回复：
{{
    "scores": {{
        "summary_quality": 8,
        "technical_depth": 6,
        "relevance": 9,
        "originality": 5,
        "formatting": 8
    }},
    "feedback": "具体的改进建议（指出弱项）",
    "weak_dimensions": ["technical_depth", "originality"]
}}

当前是第 {iteration + 1} 次审核。"""

    try:
        result, usage = chat_json(
            prompt,
            system=REVIEWER_SYSTEM,
            temperature=REVIEWER_TEMPERATURE,
        )
        tracker = accumulate_usage(tracker, usage)

        weighted_total = _weighted_score(result.get("scores", {}))
        passed = weighted_total >= pass_threshold

        feedback = str(result.get("feedback", ""))
        weak_dims = result.get("weak_dimensions", [])
        if isinstance(weak_dims, list) and weak_dims:
            feedback = f"[弱项: {', '.join(str(d) for d in weak_dims)}] {feedback}"

        logger.info(
            "[Reviewer] 加权总分: %s/10, 通过: %s (第 %d 次审核)",
            weighted_total,
            passed,
            iteration + 1,
        )
    except Exception as e:
        logger.error("[Reviewer] 审核 LLM 调用失败，自动通过: %s", e)
        passed = True
        feedback = f"审核 LLM 调用失败: {e}，自动通过"

    return {
        "review_passed": passed,
        "review_feedback": feedback,
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }
