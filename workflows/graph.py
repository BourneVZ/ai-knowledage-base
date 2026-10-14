"""LangGraph 工作流图定义 — 采集-分析-审核流水线。

工作流拓扑::

    collect → analyze → organize → review ─→ save (通过)
                           ↑                 │
                           └─────────────────┘ (未通过，最多 3 轮)

``review`` 节点通过条件边实现质量门控：审核未通过时回到 ``organize`` 重新整理，
循环次数由状态中的 ``iteration`` 累加，达到上限后由 ``review_node`` 强制通过。
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

from workflows.nodes import (  # noqa: E402
    analyze_node,
    collect_node,
    organize_node,
    review_node,
    save_node,
)
from workflows.state import KBState  # noqa: E402

logger = logging.getLogger(__name__)


def should_continue(state: KBState) -> str:
    """条件路由：根据审核结果决定下一节点。

    Args:
        state: 工作流共享状态。

    Returns:
        下一个节点名称——审核通过返回 ``"save"``，否则返回 ``"organize"``。
    """
    if state.get("review_passed", False):
        return "save"
    return "organize"


def build_graph() -> CompiledStateGraph[KBState, None, KBState, KBState]:
    """构建并编译知识库 V3 工作流图。

    Returns:
        编译后的 LangGraph 应用，可直接 ``invoke`` / ``stream`` 执行。
    """
    graph = StateGraph(KBState)

    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("organize", organize_node)
    graph.add_node("review", review_node)
    graph.add_node("save", save_node)

    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "organize")
    graph.add_edge("organize", "review")

    graph.add_conditional_edges(
        "review",
        should_continue,
        {"save": "save", "organize": "organize"},
    )

    graph.add_edge("save", END)

    graph.set_entry_point("collect")

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
        "sources": [],
        "analyses": [],
        "articles": [],
        "review_feedback": "",
        "review_passed": False,
        "iteration": 0,
        "cost_tracker": {},
    }

    final_cost: dict[str, Any] = {}

    for event in app.stream(initial_state):
        for node_name, output in event.items():
            if isinstance(output, dict) and "cost_tracker" in output:
                final_cost = output["cost_tracker"]
            if node_name == "collect":
                count = len(output.get("sources", []))
                print(f"\n--- [collect] 完成：采集 {count} 条原始数据 ---")
            elif node_name == "analyze":
                count = len(output.get("analyses", []))
                print(f"\n--- [analyze] 完成：分析 {count} 条数据 ---")
            elif node_name == "organize":
                count = len(output.get("articles", []))
                print(f"\n--- [organize] 完成：整理出 {count} 条知识条目 ---")
            elif node_name == "review":
                passed = output.get("review_passed")
                iteration = output.get("iteration")
                feedback = output.get("review_feedback", "")
                print(
                    f"\n--- [review] 完成：通过={passed}, 迭代={iteration}, "
                    f"反馈={feedback} ---"
                )
            elif node_name == "save":
                print("\n--- [save] 完成：已写入知识库 ---")
            else:
                print(f"\n--- [{node_name}] 完成 ---")

    print("\n" + "=" * 60)
    print("工作流执行完毕")
    print("=" * 60)
    print(
        "Token 用量: "
        f"prompt={final_cost.get('prompt_tokens', 0)}, "
        f"completion={final_cost.get('completion_tokens', 0)}, "
        f"估算成本≈¥{final_cost.get('total_cost_yuan', 0):.6f}"
    )
