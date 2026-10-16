"""Planner 节点 — 动态规划。

核心原则：只规划不执行（Plan, don't execute）。
Planner 的输出写入 ``state["plan"]``，被下游 Collector/Organizer/Reviewer 共同消费。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from workflows.state import KBState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

ENV_TARGET_COUNT: str = "PLANNER_TARGET_COUNT"
"""目标采集量的环境变量名。"""

DEFAULT_TARGET_COUNT: str = "10"
"""未设置环境变量时的默认目标采集量。"""


# ---------------------------------------------------------------------------
# 策略规划
# ---------------------------------------------------------------------------


def plan_strategy(target_count: int | None = None) -> dict[str, Any]:
    """根据目标采集量选择策略（三档：lite / standard / full）。

    Args:
        target_count: 目标采集量，为 ``None`` 时从环境变量
            ``PLANNER_TARGET_COUNT`` 读取（默认 10）。

    Returns:
        策略 dict，包含 ``strategy``、``per_source_limit``、
        ``relevance_threshold``、``max_iterations`` 与 ``rationale``。
    """
    if target_count is None:
        target_count = int(os.getenv(ENV_TARGET_COUNT, DEFAULT_TARGET_COUNT))

    if target_count >= 20:
        return {
            "strategy": "full",
            "per_source_limit": 20,
            "relevance_threshold": 0.4,
            "max_iterations": 3,
            "rationale": f"目标 {target_count} 条，启用深度模式（质量优先）",
        }
    if target_count >= 10:
        return {
            "strategy": "standard",
            "per_source_limit": 10,
            "relevance_threshold": 0.5,
            "max_iterations": 2,
            "rationale": f"目标 {target_count} 条，启用标准模式（平衡）",
        }
    return {
        "strategy": "lite",
        "per_source_limit": 5,
        "relevance_threshold": 0.7,
        "max_iterations": 1,
        "rationale": f"目标 {target_count} 条，启用精简模式（成本优先）",
    }


def planner_node(state: KBState) -> dict[str, Any]:
    """LangGraph 节点：把策略写入 ``state["plan"]``。

    Args:
        state: 工作流共享状态。

    Returns:
        部分状态更新，仅包含 ``plan`` 字段。
    """
    plan = plan_strategy()
    logger.info(
        "[Planner] 策略=%s, 每源=%s 条, 阈值=%s, %s",
        plan["strategy"],
        plan["per_source_limit"],
        plan["relevance_threshold"],
        plan["rationale"],
    )
    return {"plan": plan}
