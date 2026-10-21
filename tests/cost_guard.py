"""CostGuard — 多 Agent 预算守卫

三重保护：成本追踪 (record) + 预警提醒 + 预算熔断 (BudgetExceededError)
"""

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CostRecord:
    """单次 LLM 调用的成本记录"""
    timestamp: float
    node_name: str
    prompt_tokens: int
    completion_tokens: int
    cost_yuan: float
    model: str = ""


class BudgetExceededError(Exception):
    """预算超标异常 — 触发熔断"""
    pass


class CostGuard:
    """成本守卫：追踪、预警、熔断

    使用方式:
        guard = CostGuard(budget_yuan=1.0)
        guard.record("analyze", usage)   # 记录每次调用
        guard.check()                     # 检查是否超标
    """

    def __init__(
        self,
        budget_yuan: float = 1.0,
        alert_threshold: float = 0.8,
        input_price_per_million: float = 1.0,
        output_price_per_million: float = 2.0,
    ) -> None:
        self.budget_yuan = budget_yuan
        self.alert_threshold = alert_threshold
        self.input_price = input_price_per_million
        self.output_price = output_price_per_million

        self.records: list[CostRecord] = []
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_cost_yuan: float = 0.0
        self._alert_fired: bool = False

    def record(self, node_name: str, usage: dict, model: str = "") -> CostRecord:
        """记录一次 LLM 调用的 token 用量"""
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cost = (prompt_tokens * self.input_price
                + completion_tokens * self.output_price) / 1_000_000

        rec = CostRecord(
            timestamp=time.time(), node_name=node_name,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            cost_yuan=cost, model=model,
        )
        self.records.append(rec)
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_cost_yuan += cost
        return rec

    def check(self) -> dict[str, Any]:
        """检查预算状态，超标时抛出 BudgetExceededError"""
        ratio = self.total_cost_yuan / self.budget_yuan if self.budget_yuan > 0 else 0

        if self.total_cost_yuan >= self.budget_yuan:
            raise BudgetExceededError(
                f"成本已超出预算！当前: ¥{self.total_cost_yuan:.4f}, "
                f"预算: ¥{self.budget_yuan:.2f}"
            )

        if ratio >= self.alert_threshold and not self._alert_fired:
            self._alert_fired = True
            status = "warning"
            message = f"[预警] 成本已达预算的 {ratio:.0%}！"
        else:
            status = "ok"
            message = f"成本正常: ¥{self.total_cost_yuan:.4f} / ¥{self.budget_yuan:.2f}"

        return {"status": status, "total_cost": round(self.total_cost_yuan, 6),
                "budget": self.budget_yuan, "usage_ratio": round(ratio, 4), "message": message}

    def get_report(self) -> dict:
        """生成成本报告（按节点分组统计）"""
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


# --- 测试入口 ---
if __name__ == "__main__":
    print("=== 测试 1：成本追踪 ===")
    guard = CostGuard(budget_yuan=1.0)
    guard.record("collect", {"prompt_tokens": 100, "completion_tokens": 50})
    guard.record("analyze", {"prompt_tokens": 2000, "completion_tokens": 1000})
    guard.record("review", {"prompt_tokens": 2500, "completion_tokens": 800})
    report = guard.get_report()
    print(f"  调用次数: {report['total_calls']}")
    print(f"  总成本: ¥{report['total_cost_yuan']}")
    print(f"  按节点: {report['cost_by_node']}")
    result = guard.check()
    print(f"  预算状态: {result['status']}\n")

    print("=== 测试 2：预算超限 ===")
    guard2 = CostGuard(budget_yuan=0.001)
    guard2.record("analyze", {"prompt_tokens": 100000, "completion_tokens": 100000})
    try:
        guard2.check()
        assert False, "应该抛出 BudgetExceededError！"
    except BudgetExceededError as e:
        print(f"  预算超限检测通过: {e}\n")

    print("=== 测试 3：预警阈值 ===")
    guard3 = CostGuard(budget_yuan=0.01, alert_threshold=0.5)
    guard3.record("analyze", {"prompt_tokens": 5000, "completion_tokens": 2000})
    result3 = guard3.check()
    print(f"  预警状态: {result3['status']} — {result3['message']}\n")

    print("所有测试通过！")