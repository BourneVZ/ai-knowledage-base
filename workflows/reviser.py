"""Reviser 节点 — 定向修改（只修改不评估）。

Reviser 与 Reviewer 是两个独立 Agent，避免 Reviewer 给自己打高分：
Reviewer 只给分与反馈，Reviser 只按反馈定向修改 ``analyses``，职责隔离。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pipeline.model_client import accumulate_usage, chat_json
from workflows.state import KBState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

REVISER_SYSTEM: str = "你是经验丰富的知识库编辑。根据反馈定向修改，不要过度发散。"
"""Reviser 系统提示词。"""

REVISER_TEMPERATURE: float = 0.4
"""修改采样温度，允许一定的创造性改写。"""

REVISER_TIMEOUT: float = 180.0
"""修改调用的超时（秒）。

修正需一次性携带全部 analyses 与审核反馈并重写 JSON 数组，输入输出都较大，
故使用比默认 60s 更长的超时，避免重写频繁超时。
"""

REVISER_MAX_TOKENS: int = 8192
"""修改调用的最大生成 token 数，避免重写多条目时被截断。"""


# ---------------------------------------------------------------------------
# 节点定义
# ---------------------------------------------------------------------------


def revise_node(state: KBState) -> dict[str, Any]:
    """Reviser 节点：根据 Reviewer 反馈定向修改 ``analyses``。

    Args:
        state: 工作流共享状态。

    Returns:
        部分状态更新——成功时返回 ``{"analyses": revised, "cost_tracker": tracker}``；
        无可修改内容时返回 ``{}``；LLM 失败或结果无效时仅返回累加后的
        ``cost_tracker``（保留原 ``analyses``）。
    """
    analyses = state["analyses"]
    feedback = state["review_feedback"]
    iteration = state["iteration"]
    tracker = state["cost_tracker"]

    if not analyses or not feedback:
        logger.info("[Reviser] 无可修改内容，跳过")
        return {}

    prompt = f"""你是知识库编辑。以下是审核员的反馈，请据此修改这些分析结果。

【审核反馈】
{feedback}

【当前分析结果】
{json.dumps(analyses, ensure_ascii=False, indent=2)}

【修改要求】
- 重点改进反馈中提到的弱项维度
- 保留已经不错的部分
- 保持相同字段结构
- 返回修改后的 JSON 数组"""

    try:
        improved, usage = chat_json(
            prompt,
            system=REVISER_SYSTEM,
            temperature=REVISER_TEMPERATURE,
            timeout=REVISER_TIMEOUT,
            max_tokens=REVISER_MAX_TOKENS,
        )
        tracker = accumulate_usage(tracker, usage)
    except Exception as e:
        logger.warning("[Reviser] 修改失败，保留原 analyses: %s", e)
        return {"cost_tracker": tracker}

    if not isinstance(improved, list):
        logger.warning("[Reviser] 修改结果不是 JSON 数组，保留原 analyses")
        return {"cost_tracker": tracker}

    revised = [i for i in improved if isinstance(i, dict)]
    if not revised:
        logger.warning("[Reviser] 修改结果无有效条目，保留原 analyses")
        return {"cost_tracker": tracker}

    logger.info("[Reviser] 定向修改 %d 条 analyses (迭代 %d)", len(revised), iteration)
    return {"analyses": revised, "cost_tracker": tracker}
