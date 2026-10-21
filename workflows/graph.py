"""LangGraph 工作流图定义 — 规划-采集-分析-审核-人工介入流水线。

工作流拓扑::

    plan → collect → analyze → review ──通过────→ organize → END
                                     ├─未通过──→ revise → review (循环)
                                     └─超限────→ human_flag → END

``plan`` 节点在入口产出策略（写入 ``state["plan"]``），下游按策略调整采集量、
过滤阈值与审核循环上限；``review`` 通过三路条件边实现质量门控，超限转人工介入。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

# 支持 `python workflows/graph.py` 直接运行：脚本模式下 sys.path[0] 是脚本所在
# 目录（workflows/），需额外加入项目根目录才能解析 `workflows.*` 与 `pipeline.*`。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.llm import get_cost_guard  # noqa: E402
from safeguards.cost_guard import BudgetExceededError  # noqa: E402
from workflows.analyzer import analyze_node  # noqa: E402
from workflows.collector import collect_node  # noqa: E402
from workflows.human_flag import human_flag_node  # noqa: E402
from workflows.organizer import organize_node  # noqa: E402
from workflows.planner import planner_node  # noqa: E402
from workflows.reviewer import review_node  # noqa: E402
from workflows.reviser import revise_node  # noqa: E402
from workflows.state import KBState  # noqa: E402

logger = logging.getLogger(__name__)


DEFAULT_MAX_ITERATIONS: int = 3
"""plan 未指定 max_iterations 时的兜底值。"""


def route_after_review(state: KBState) -> str:
    """条件路由：读 ``state["plan"]["max_iterations"]``，不再硬编码 3。

    Args:
        state: 工作流共享状态。

    Returns:
        下一个节点名称——``"organize"``（通过）、``"revise"``（未通过且未超限）、
        ``"human_flag"``（未通过且达到上限）。
    """
    plan = state.get("plan") or {}
    max_iterations = int(plan.get("max_iterations", DEFAULT_MAX_ITERATIONS))
    iteration = state.get("iteration", 0)

    if state.get("review_passed", False):
        return "organize"
    if iteration >= max_iterations:
        return "human_flag"
    return "revise"


def build_graph() -> CompiledStateGraph[KBState, None, KBState, KBState]:
    """构建并编译知识库 V3 工作流图。

    Returns:
        编译后的 LangGraph 应用，可直接 ``invoke`` / ``stream`` 执行。
    """
    graph = StateGraph(KBState)

    graph.add_node("plan", planner_node)
    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("review", review_node)
    graph.add_node("revise", revise_node)
    graph.add_node("organize", organize_node)
    graph.add_node("human_flag", human_flag_node)

    graph.add_edge("plan", "collect")
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "review")

    graph.add_conditional_edges(
        "review",
        route_after_review,
        {
            "organize": "organize",
            "revise": "revise",
            "human_flag": "human_flag",
        },
    )

    graph.add_edge("revise", "review")
    graph.add_edge("organize", END)
    graph.add_edge("human_flag", END)

    graph.set_entry_point("plan")

    return graph.compile()


app = build_graph()


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s | %(name)s | %(message)s",
    )

    print("=" * 60)
    print("AI 知识库 — LangGraph 工作流启动")
    print("=" * 60)

    initial_state: KBState = {
        "plan": {},
        "sources": [],
        "analyses": [],
        "articles": [],
        "review_feedback": "",
        "review_passed": False,
        "needs_human_review": False,
        "iteration": 0,
        "cost_tracker": {},
    }

    final_cost: dict[str, Any] = {}
    guard = get_cost_guard()

    try:
        for event in app.stream(initial_state):
            for node_name, output in event.items():
                if isinstance(output, dict) and "cost_tracker" in output:
                    final_cost = output["cost_tracker"]
                if node_name == "plan":
                    plan = output.get("plan", {})
                    print(
                        f"\n--- [plan] 完成：策略={plan.get('strategy')}, "
                        f"GitHub每页={plan.get('github_limit')} 条, "
                        f"创新分阈值={plan.get('min_innovation_score')} ---"
                    )
                elif node_name == "collect":
                    count = len(output.get("sources", []))
                    print(f"\n--- [collect] 完成：采集 {count} 条原始数据 ---")
                elif node_name == "analyze":
                    count = len(output.get("analyses", []))
                    print(f"\n--- [analyze] 完成：分析 {count} 条数据 ---")
                elif node_name == "organize":
                    count = len(output.get("articles", []))
                    print(f"\n--- [organize] 完成：整理并保存 {count} 条知识条目 ---")
                elif node_name == "review":
                    passed = output.get("review_passed")
                    iteration = output.get("iteration")
                    feedback = output.get("review_feedback", "")
                    print(
                        f"\n--- [review] 完成：通过={passed}, 迭代={iteration}, "
                        f"反馈={feedback} ---"
                    )
                elif node_name == "revise":
                    count = len(output.get("analyses", []))
                    print(f"\n--- [revise] 完成：定向修改 {count} 条 analyses ---")
                elif node_name == "human_flag":
                    print("\n--- [human_flag] 完成：已转人工介入 ---")
                else:
                    print(f"\n--- [{node_name}] 完成 ---")
    except BudgetExceededError as e:
        print(f"\n[预算熔断] 本次运行已中止: {e}")
    finally:
        report = guard.get_report()
        print("\n" + "=" * 60)
        print("成本守卫报告（CostGuard）")
        print("-" * 60)
        print(f"  预算: ¥{report['budget_yuan']:.2f}")
        print(f"  调用次数: {report['total_calls']}")
        print(f"  输入 tokens: {report['total_prompt_tokens']:,}")
        print(f"  输出 tokens: {report['total_completion_tokens']:,}")
        print(f"  累计成本: ¥{report['total_cost_yuan']:.6f}")
        if report["cost_by_node"]:
            print(f"  按节点成本: {report['cost_by_node']}")

    print("\n" + "=" * 60)
    print("工作流执行完毕")
    print("=" * 60)
    print(
        "Token 用量: "
        f"prompt={final_cost.get('prompt_tokens', 0)}, "
        f"completion={final_cost.get('completion_tokens', 0)}, "
        f"估算成本≈¥{final_cost.get('total_cost_yuan', 0):.6f}"
    )
