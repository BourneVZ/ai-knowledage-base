"""Analyzer 节点 — 用 LLM 对每条采集数据生成结构化分析。

输入 ``state["sources"]``，逐条调用 LLM 分析，输出结构化 ``analyses``。
分析 schema 与 V2/Agent 对齐：``summary``/``tags``/``category``/
``innovation_score``(1-5)/``difficulty_score``(1-5)/``key_points``/``risks``。
"""

from __future__ import annotations

import logging
from typing import Any

from core.llm import accumulate_usage, chat_json
from workflows.state import KBState

logger = logging.getLogger(__name__)


def analyze_node(state: KBState) -> dict[str, Any]:
    """分析节点：用 LLM 对每条数据生成摘要、标签、评分、亮点与风险。

    Args:
        state: 工作流共享状态。

    Returns:
        部分状态更新，包含 ``analyses`` 和累加后的 ``cost_tracker``。
    """
    logger.info("[Analyzer] 开始分析 %d 条数据", len(state["sources"]))
    analyses: list[dict[str, Any]] = []
    tracker = state["cost_tracker"]

    for item in state["sources"]:
        title = str(item.get("title", ""))
        if not title:
            continue

        prompt = f"""请分析以下技术项目，用 JSON 格式返回（仅输出 JSON，不要 markdown 代码块）：

项目名: {title}
描述: {item.get("description", "无描述")}
来源: {item.get("source", "")}

返回格式:
{{
    "summary": "200字中文摘要",
    "tags": ["ai", "llm"],
    "category": "AI Agent",
    "innovation_score": 4,
    "difficulty_score": 3,
    "key_points": ["核心亮点1", "核心亮点2"],
    "risks": ["潜在风险1"]
}}

说明：
- innovation_score / difficulty_score 为 1-5 整数
- tags 为 3-5 个英文小写标签
- key_points 为 2-3 个核心亮点（中文短语）
- risks 为 1-2 个潜在局限（中文短语，如无则空数组）"""

        try:
            result, usage = chat_json(prompt)
            tracker = accumulate_usage(tracker, usage)
            analyses.append({**item, **result})
        except Exception as e:
            logger.error("[Analyzer] 分析失败: %s - %s", title, e)
            analyses.append(
                {
                    **item,
                    "summary": f"分析失败: {e}",
                    "innovation_score": 0,
                    "difficulty_score": 0,
                    "key_points": [],
                    "risks": [],
                }
            )

    logger.info("[Analyzer] 完成 %d 条分析", len(analyses))
    return {"analyses": analyses, "cost_tracker": tracker}
