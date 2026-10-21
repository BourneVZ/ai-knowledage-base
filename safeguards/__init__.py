"""safeguards — 安全与预算防护组件包。

生产代码从这里导入 CostGuard（预算守卫）与 Security（输入清洗 / PII 过滤 /
限流 / 审计）。流水线接入点见各模块 docstring。

Usage::

    from safeguards.cost_guard import BudgetExceededError, CostGuard
    from safeguards.security import filter_output, sanitize_input
"""

from safeguards.cost_guard import BudgetExceededError, CostGuard, CostRecord
from safeguards.security import (
    AuditEntry,
    AuditEventType,
    AuditLogger,
    RateLimiter,
    filter_output,
    sanitize_input,
)

__all__ = [
    "AuditEntry",
    "AuditEventType",
    "AuditLogger",
    "BudgetExceededError",
    "CostGuard",
    "CostRecord",
    "RateLimiter",
    "filter_output",
    "sanitize_input",
]
