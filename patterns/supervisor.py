"""Supervisor 监督模式 — Worker 执行 + Supervisor 审核 + 反馈修正循环

核心设计：
- Worker 只负责执行，Supervisor 只负责审核（职责隔离）
- 审核反馈结构化（评分 + 弱项 + 建议），支持定向修改
- max_retries=3 兜底，避免无限循环
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

# 支持 `python patterns/supervisor.py` 直接运行：脚本模式下 sys.path[0] 是脚本
# 所在目录（patterns/），需额外加入项目根目录才能解析 `core.*`。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.llm import Usage, chat_with_retry  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# chat 适配器（与 workflow 接口签名一致）
# ---------------------------------------------------------------------------


def chat(
    prompt: str,
    *,
    system: str = "",
    max_tokens: int = 4096,
    temperature: float | None = None,
) -> tuple[str, Usage]:
    """发送聊天请求，返回 ``(文本, Usage)`` 元组。

    Args:
        prompt: 用户提示词。
        system: 系统提示词。
        max_tokens: 最大生成 token 数。
        temperature: 采样温度，为 ``None`` 时使用默认值。

    Returns:
        ``(response_text, Usage)`` 元组。
    """
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    kwargs: dict[str, Any] = {"max_tokens": max_tokens}
    if temperature is not None:
        kwargs["temperature"] = temperature
    response = chat_with_retry(messages, **kwargs)
    return response.content, response.usage


# ---------------------------------------------------------------------------
# 系统 Prompt
# ---------------------------------------------------------------------------

WORKER_SYSTEM = """你是 AI 技术分析师。请按要求完成分析任务。
输出 JSON 格式，包含：summary, key_points, recommendation。"""

SUPERVISOR_SYSTEM = """你是质量审核专家。请审核以下分析报告。

评分维度（每维度 1-10）：
1. 准确性：信息是否准确无误
2. 深度：分析是否有洞察力
3. 格式：是否符合 JSON 规范，结构清晰

输出严格 JSON：
{"passed": true/false, "score": 1-10总分, "feedback": "具体改进建议"}
只输出 JSON，不要其他内容。"""


# ---------------------------------------------------------------------------
# Supervisor 主函数
# ---------------------------------------------------------------------------


def supervisor(task: str, max_retries: int = 3) -> dict[str, Any]:
    """监督模式：Worker 产出 + Supervisor 审核，不通过就重做。

    Args:
        task: 分析任务描述。
        max_retries: 最大重试次数。

    Returns:
        包含以下字段的字典:
        - ``output``: Worker 最终产出的文本。
        - ``attempts``: 实际执行轮次。
        - ``final_score``: 最终审核得分（0-10）。
        - ``warning``: 仅在达到最大重试次数时存在，提示质量可能不达标。
    """
    worker_output: str = ""
    feedback: str = ""

    for attempt in range(1, max_retries + 1):
        # --- Worker 执行 ---
        if attempt == 1:
            worker_output, _ = chat(task, system=WORKER_SYSTEM)
        else:
            revision_prompt = (
                f"原始任务: {task}\n\n"
                f"上次产出: {worker_output}\n\n"
                f"审核反馈: {feedback}\n\n"
                f"请根据反馈改进，保持 JSON 格式。"
            )
            worker_output, _ = chat(revision_prompt, system=WORKER_SYSTEM)

        # --- Supervisor 审核 ---
        review_prompt = f"请审核以下分析报告：\n{worker_output}"
        review_text, _ = chat(
            review_prompt,
            system=SUPERVISOR_SYSTEM,
            temperature=0.2,
        )

        try:
            review_data: dict[str, Any] = json.loads(review_text)
        except json.JSONDecodeError:
            logger.warning(
                "审核输出 JSON 解析失败，第 %d 轮。原文: %s",
                attempt,
                review_text[:200],
            )
            review_data = {"passed": False, "score": 0, "feedback": "审核输出格式错误"}

        score_raw: int | float | str = review_data.get("score", 0)
        try:
            score = int(score_raw)
        except (ValueError, TypeError):
            score = 0

        feedback = str(review_data.get("feedback", "请改进质量"))
        print(f"  第 {attempt} 轮审核: 得分 {score}/10")

        # --- 判断是否通过 ---
        passed: object = review_data.get("passed")
        if passed is True or score >= 7:
            return {
                "output": worker_output,
                "attempts": attempt,
                "final_score": score,
            }

    # 达到最大重试次数
    return {
        "output": worker_output,
        "attempts": max_retries,
        "final_score": score,
        "warning": f"达到最大重试次数({max_retries})，可能质量不达标",
    }


# ---------------------------------------------------------------------------
# 测试入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s | %(name)s | %(message)s",
    )

    task = (
        " ".join(sys.argv[1:])
        if len(sys.argv) > 1
        else "请分析 LangGraph 框架的优缺点和适用场景"
    )

    print("=" * 50)
    print("Supervisor 监督模式测试")
    print("=" * 50)
    print(f"\n任务: {task}\n")

    result = supervisor(task)

    print("\n最终结果:")
    print(f"  审核轮次: {result['attempts']}")
    print(f"  最终得分: {result['final_score']}/10")
    if result.get("warning"):
        print(f"  警告: {result['warning']}")
    print(f"  输出预览: {result['output'][:200]}...")
