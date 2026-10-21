"""CostGuard — 多 Agent 预算守卫（成本追踪 + 预警 + 预算熔断）。

被 ``core.llm.chat`` 在每次 LLM 调用完成后调用：``record`` 累计 token 成本，
``check`` 在累计成本超出预算时抛出 :class:`BudgetExceededError` 熔断流水线。

预算通过环境变量 ``BUDGET_YUAN`` 配置（由 ``core.llm.get_cost_guard`` 读取），
计价单位为元/百万 tokens。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class UsageLike(Protocol):
    """LLM 用量对象协议。

    ``core.llm.Usage`` dataclass 及任何带 ``prompt_tokens`` /
    ``completion_tokens`` 属性的结构均满足该协议。
    """

    prompt_tokens: int
    completion_tokens: int


@dataclass
class CostRecord:
    """单次 LLM 调用的成本记录。"""

    timestamp: float
    node_name: str
    prompt_tokens: int
    completion_tokens: int
    cost_yuan: float
    model: str = ""


class BudgetExceededError(Exception):
    """预算超标异常 — 触发熔断。"""


class CostGuard:
    """成本守卫：追踪、预警、熔断。

    Usage::

        guard = CostGuard(budget_yuan=1.0)
        guard.record("analyze", usage)   # 记录每次调用
        guard.check()                    # 检查是否超标
    """

    def __init__(
        self,
        budget_yuan: float = 1.0,
        alert_threshold: float = 0.8,
        input_price_per_million: float = 1.0,
        output_price_per_million: float = 2.0,
    ) -> None:
        """初始化守卫。

        Args:
            budget_yuan: 单次运行的预算上限（元），累计成本达到即熔断。
            alert_threshold: 预警阈值（占预算比例），触发时打 warning 日志。
            input_price_per_million: 输入 token 计价（元/百万 tokens）。
            output_price_per_million: 输出 token 计价（元/百万 tokens）。
        """
        self.budget_yuan = budget_yuan
        self.alert_threshold = alert_threshold
        self.input_price = input_price_per_million
        self.output_price = output_price_per_million

        self.records: list[CostRecord] = []
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_cost_yuan: float = 0.0
        self._alert_fired: bool = False

    def record(self, node_name: str, usage: UsageLike, model: str = "") -> CostRecord:
        """记录一次 LLM 调用的 token 用量与成本。

        Args:
            node_name: 发起调用的节点名（如 ``"analyze"``、``"review"``）。
            usage: LLM 返回的用量对象（见 :class:`UsageLike`）。
            model: 实际使用的模型名。

        Returns:
            已登记的 :class:`CostRecord`。
        """
        prompt_tokens = usage.prompt_tokens
        completion_tokens = usage.completion_tokens
        cost = (
            prompt_tokens * self.input_price + completion_tokens * self.output_price
        ) / 1_000_000

        rec = CostRecord(
            timestamp=time.time(),
            node_name=node_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_yuan=cost,
            model=model,
        )
        self.records.append(rec)
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_cost_yuan += cost

        logger.debug(
            "CostGuard 记录: node=%s, prompt=%d, completion=%d, cost=¥%.6f, "
            "累计=¥%.6f/¥%.2f",
            node_name,
            prompt_tokens,
            completion_tokens,
            cost,
            self.total_cost_yuan,
            self.budget_yuan,
        )
        return rec

    def check(self) -> dict[str, Any]:
        """检查预算状态，超标时抛出 :class:`BudgetExceededError`。

        Returns:
            状态字典：``{"status", "total_cost", "budget", "usage_ratio",
            "message"}``，``status`` 为 ``"ok"`` 或 ``"warning"``。
        """
        ratio = self.total_cost_yuan / self.budget_yuan if self.budget_yuan > 0 else 0

        if self.total_cost_yuan >= self.budget_yuan:
            logger.error(
                "预算熔断！当前: ¥%.6f, 预算: ¥%.2f, 调用 %d 次",
                self.total_cost_yuan,
                self.budget_yuan,
                len(self.records),
            )
            raise BudgetExceededError(
                f"成本已超出预算！当前: ¥{self.total_cost_yuan:.4f}, "
                f"预算: ¥{self.budget_yuan:.2f}"
            )

        if ratio >= self.alert_threshold and not self._alert_fired:
            self._alert_fired = True
            status = "warning"
            message = f"[预警] 成本已达预算的 {ratio:.0%}！"
            logger.warning("CostGuard %s", message)
        else:
            status = "ok"
            message = f"成本正常: ¥{self.total_cost_yuan:.4f} / ¥{self.budget_yuan:.2f}"

        return {
            "status": status,
            "total_cost": round(self.total_cost_yuan, 6),
            "budget": self.budget_yuan,
            "usage_ratio": round(ratio, 4),
            "message": message,
        }

    def get_report(self) -> dict[str, Any]:
        """生成成本报告（按节点分组统计）。

        Returns:
            报告字典，含总成本、总 tokens、调用次数与 ``cost_by_node`` 明细。
        """
        by_node: dict[str, float] = {}
        for r in self.records:
            by_node[r.node_name] = by_node.get(r.node_name, 0) + r.cost_yuan
        return {
            "total_cost_yuan": round(self.total_cost_yuan, 6),
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_calls": len(self.records),
            "budget_yuan": self.budget_yuan,
            "cost_by_node": {k: round(v, 6) for k, v in by_node.items()},
        }


# --- 自测入口 ---
if __name__ == "__main__":
    from dataclasses import dataclass as _dc

    @_dc
    class _FakeUsage:
        prompt_tokens: int
        completion_tokens: int

    print("=== 测试 1：成本追踪 ===")
    guard = CostGuard(budget_yuan=1.0)
    guard.record("collect", _FakeUsage(100, 50))
    guard.record("analyze", _FakeUsage(2000, 1000))
    guard.record("review", _FakeUsage(2500, 800))
    report = guard.get_report()
    print(f"  调用次数: {report['total_calls']}")
    print(f"  总成本: ¥{report['total_cost_yuan']}")
    print(f"  按节点: {report['cost_by_node']}")
    result = guard.check()
    print(f"  预算状态: {result['status']}\n")

    print("=== 测试 2：预算超限 ===")
    guard2 = CostGuard(budget_yuan=0.001)
    guard2.record("analyze", _FakeUsage(100000, 100000))
    try:
        guard2.check()
        raise SystemExit("FAIL: 应该抛出 BudgetExceededError！")
    except BudgetExceededError as e:
        print(f"  预算超限检测通过: {e}\n")

    print("=== 测试 3：预警阈值 ===")
    guard3 = CostGuard(budget_yuan=0.01, alert_threshold=0.5)
    guard3.record("analyze", _FakeUsage(5000, 2000))
    result3 = guard3.check()
    print(f"  预警状态: {result3['status']} — {result3['message']}\n")

    print("所有测试通过！")
