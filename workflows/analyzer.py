"""Analyzer 节点 — 用 LLM 对每条采集数据生成中文摘要、标签、评分。

输入 ``state["sources"]``，逐条调用 LLM 分析，输出结构化 ``analyses``
（每条含 summary、tags、relevance_score、category、key_insight）。
"""

from __future__ import annotations

import logging
from typing import Any

from pipeline.model_client import accumulate_usage, chat_json
from workflows.state import KBState

logger = logging.getLogger(__name__)


def analyze_node(state: KBState) -> dict[str, Any]:
    """分析节点：用 LLM 对每条数据生成中文摘要、标签、评分。

    Args:
        state: 工作流共享状态。

    Returns:
        部分状态更新，包含 ``analyses`` 和累加后的 ``cost_tracker``。
    """
    logger.info("[Analyzer] 开始分析 %d 条数据", len(state["sources"]))
    analyses: list[dict[str, Any]] = []
    tracker = state["cost_tracker"]

    for item in state["sources"]:
        if str(item.get("title", "")).startswith("[ERROR]"):
            continue

        prompt = f"""请分析以下技术项目，用 JSON 格式返回：
项目名: {item.get("title", "")}
描述: {item.get("description", "无描述")}

返回格式: {{"summary": "200字中文摘要", "tags": ["标签"], "relevance_score": 0.8, "category": "分类", "key_insight": "一句话洞察"}}"""

        try:
            result, usage = chat_json(prompt)
            tracker = accumulate_usage(tracker, usage)
            analyses.append({**item, **result})
        except Exception as e:
            logger.error("[Analyzer] 分析失败: %s - %s", item.get("title"), e)
            analyses.append(
                {**item, "summary": f"分析失败: {e}", "relevance_score": 0.0}
            )

    logger.info("[Analyzer] 完成 %d 条分析", len(analyses))
    return {"analyses": analyses, "cost_tracker": tracker}
