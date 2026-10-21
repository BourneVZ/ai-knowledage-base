"""Eval 评估测试 — AI 知识库质量验证

核心原则：
- 不测精确内容，测行为边界
- 用 >=, <=, in 代替 ==
- 正面 + 负面 + 边界 = 最小 Eval 集
- LLM-as-Judge 做质量评分

运行方式：
- 本地结构验证（不消耗 token）: ``pytest tests/eval_test.py -m "not slow" -v``
- LLM 评估（消耗 token）: ``pytest tests/eval_test.py -m slow -v``
"""

import logging
import os
import re
import sys
import warnings
from typing import TypedDict

import pytest
from dotenv import load_dotenv

# 确保可以导入 core 模块
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 加载 .env，让 pytest 能读到 LLM_API_KEY
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# 屏蔽 "Unknown pytest.mark.slow" 警告（slow 是自定义慢速标记，未注册到 ini）
warnings.filterwarnings("ignore", category=pytest.PytestUnknownMarkWarning)

from core.llm import chat  # noqa: E402

logger = logging.getLogger(__name__)

# ── 评估用例定义 ──────────────────────────────────────────

LABEL_POSITIVE = "正面"
LABEL_NEGATIVE = "负面"
LABEL_BOUNDARY = "边界"

IRRELEVANT_MARKERS: tuple[str, ...] = ("不相关", "无关")


class EvalExpectation(TypedDict, total=False):
    """单个评估用例的预期条件，全部为范围性检查。"""

    min_length: int
    max_length: int
    must_contain_any: list[str]
    should_mention_irrelevant: bool
    no_crash: bool


class EvalCase(TypedDict):
    """单个评估用例：名称、输入与预期条件。"""

    name: str
    input: str
    expected: EvalExpectation


EVAL_CASES: list[EvalCase] = [
    {
        "name": f"{LABEL_POSITIVE}案例 — 技术项目分析",
        "input": (
            "LangGraph 是一个基于有向图的多 Agent 工作流编排框架，支持条件分支和循环。"
        ),
        "expected": {
            "min_length": 50,
            "max_length": 1000,
            "must_contain_any": ["LangGraph", "工作流", "Agent", "图"],
        },
    },
    {
        "name": f"{LABEL_NEGATIVE}案例 — 无关内容",
        "input": "今天天气真好，适合出去野餐，带上三明治和果汁。",
        "expected": {
            "max_length": 500,
            "should_mention_irrelevant": True,
        },
    },
    {
        "name": f"{LABEL_BOUNDARY}案例 — 极短输入",
        "input": "AI",
        "expected": {
            "min_length": 1,
            "no_crash": True,
        },
    },
    {
        "name": f"{LABEL_POSITIVE}案例 — 英文技术内容",
        "input": (
            "OpenAI released GPT-5 with 1M token context window and native tool use."
        ),
        "expected": {
            "min_length": 30,
            "max_length": 1000,
            "must_contain_any": ["GPT-5", "OpenAI", "token", "context"],
        },
    },
]


# ── 本地验证（不调 LLM）──────────────────────────────────


def test_eval_cases_structure() -> None:
    """验证 EVAL_CASES 的结构完整性（不消耗 token）。"""
    assert len(EVAL_CASES) >= 3, "至少需要 3 个评估用例"

    names = [c["name"] for c in EVAL_CASES]
    assert any(LABEL_POSITIVE in n for n in names), "缺少正面案例"
    assert any(LABEL_NEGATIVE in n for n in names), "缺少负面案例"
    assert any(LABEL_BOUNDARY in n for n in names), "缺少边界案例"

    for case in EVAL_CASES:
        assert "name" in case, "用例缺少 name 字段"
        assert "input" in case, f"用例 {case.get('name')} 缺少 input"
        assert "expected" in case, f"用例 {case.get('name')} 缺少 expected"
        assert case["input"], f"用例 {case['name']} 的 input 不应为空"
        assert len(case["expected"]) > 0, f"用例 {case['name']} 缺少预期条件"


# ── LLM 评估测试（消耗 token）────────────────────────────


@pytest.mark.slow
def test_eval_positive() -> None:
    """正面案例：技术内容应生成有意义的分析。"""
    case = EVAL_CASES[0]
    prompt = f"请分析以下技术内容，输出 200 字以内的中文摘要：\n{case['input']}"
    result, usage = chat(prompt, system="你是技术分析师。")

    expected = case["expected"]
    assert len(result) >= expected["min_length"], (
        f"输出太短: {len(result)} < {expected['min_length']}"
    )
    assert len(result) <= expected["max_length"], (
        f"输出太长: {len(result)} > {expected['max_length']}"
    )
    assert usage.total_tokens >= 0, "应返回有效的 Usage 统计"

    found = any(kw in result for kw in expected["must_contain_any"])
    assert found, f"输出应包含以下关键词之一: {expected['must_contain_any']}"


@pytest.mark.slow
def test_eval_negative() -> None:
    """负面案例：无关内容应被识别为不相关。"""
    case = EVAL_CASES[1]
    prompt = (
        "判断以下内容是否与 AI/LLM/Agent 技术相关。\n"
        "要求：回答必须以【相关】或【不相关】开头，再用一句话说明理由。\n\n"
        f"内容：{case['input']}"
    )
    result, _ = chat(prompt, system="你是技术内容筛选器。")

    expected = case["expected"]
    assert 0 < len(result) <= expected["max_length"], (
        f"输出长度应在 (0, {expected['max_length']}] 内，实际: {len(result)}"
    )

    found_irrelevant = any(kw in result for kw in IRRELEVANT_MARKERS)
    assert found_irrelevant, f"无关内容应被标记为低相关，实际输出: {result[:100]}"


@pytest.mark.slow
def test_eval_boundary() -> None:
    """边界案例：极短输入不应崩溃。"""
    case = EVAL_CASES[2]
    try:
        result, _ = chat(f"请分析：{case['input']}", system="你是技术分析师。")
        assert result is not None
        assert len(result) >= case["expected"]["min_length"], (
            f"输出不应为空: {result!r}"
        )
    except Exception as e:
        pytest.fail(f"边界输入不应导致崩溃: {e}")


@pytest.mark.slow
def test_llm_as_judge() -> None:
    """LLM-as-Judge：让 LLM 对分析质量打分（1-10）。"""
    # 先生成分析结果
    analysis, _ = chat(
        "请分析 LangGraph 框架的核心优势和适用场景",
        system="你是技术分析师。输出 Markdown 格式。",
    )

    # 让另一次 LLM 调用评分
    judge_prompt = f"""请对以下技术分析的质量打分（1-10分）。

分析内容：
{analysis}

评分标准：
- 准确性：信息是否正确
- 深度：是否有洞察
- 实用性：读者能否据此行动

只返回一个数字（1-10），不要解释。"""

    score_text, _ = chat(
        judge_prompt,
        system="你是质量评审。只返回数字。",
        max_tokens=10,
    )

    try:
        score = int(score_text.strip())
    except ValueError:
        match = re.search(r"\d+", score_text)
        score = int(match.group()) if match else 0

    assert 1 <= score <= 10, f"评分应在 1-10 范围内，实际: {score}"
    assert score >= 5, f"分析质量评分过低: {score}/10"
    logger.info("LLM-as-Judge 评分: %d/10", score)


# ── 运行入口 ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=== 本地验证（不消耗 token）===")
    test_eval_cases_structure()
    print(f"[OK] EVAL_CASES 结构验证通过，共 {len(EVAL_CASES)} 个用例")
    for c in EVAL_CASES:
        print(f"  - {c['name']}")

    print("\n提示：运行 LLM 测试请使用:")
    print("  pytest tests/eval_test.py -m slow -v")
