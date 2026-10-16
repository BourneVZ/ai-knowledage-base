"""Planner 节点 — 动态规划。

核心原则：只规划不执行（Plan, don't execute）。
Planner 通过 :func:`pipeline.config.resolve_plan` 读取 ``config.yaml`` 选择档位，
写入 ``state["plan"]``，被下游 Collector/Organizer/Reviewer 共同消费。
"""

from __future__ import annotations

import logging
from typing import Any

from pipeline.config import resolve_plan
from workflows.state import KBState

logger = logging.getLogger(__name__)


def planner_node(state: KBState) -> dict[str, Any]:
    """LangGraph 节点：把策略写入 ``state["plan"]``。

    Args:
        state: 工作流共享状态。

    Returns:
        部分状态更新，仅包含 ``plan`` 字段。
    """
    plan = resolve_plan()
    logger.info(
        "[Planner] 策略=%s, GitHub每页=%s 条, 创新分阈值=%s, %s",
        plan["strategy"],
        plan["github_limit"],
        plan["min_innovation_score"],
        plan["rationale"],
    )
    return {"plan": plan}
