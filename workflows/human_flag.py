"""HumanFlag 节点 — 人工介入（异常终点）。

审核循环超过上限仍未通过，说明问题不在「质量」而在「数据」，需要人工判断。
HumanFlag 节点把问题条目写入独立目录 ``knowledge/pending_review/``，不污染主知识库。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from workflows.state import KBState

logger = logging.getLogger(__name__)


def human_flag_node(state: KBState) -> dict[str, Any]:
    """审核循环超过上限时的兜底 —— 写入 ``pending_review/`` 目录。

    Args:
        state: 工作流共享状态。

    Returns:
        部分状态更新，仅包含 ``needs_human_review=True``。
    """
    analyses = state["analyses"]
    iteration = state["iteration"]
    feedback = state["review_feedback"]

    logger.warning("[HumanFlag] 达到 %d 次审核仍未通过，转人工处理", iteration)
    logger.warning("[HumanFlag] 最后反馈: %s", feedback[:200])

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pending_dir = os.path.join(base_dir, "knowledge", "pending_review")
    os.makedirs(pending_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    filepath = os.path.join(pending_dir, f"pending-{timestamp}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": timestamp,
                "iterations_used": iteration,
                "last_feedback": feedback,
                "analyses": analyses,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    logger.info("[HumanFlag] 已保存到 %s", filepath)
    return {"needs_human_review": True}
