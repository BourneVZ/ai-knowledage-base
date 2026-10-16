"""Collector 节点 — 从 GitHub Search API 采集 AI 相关仓库。

产出报告式摘要（``title``/``url``/``description``/``stars`` 等），不携带原始
API 全量响应；采集数量由 ``state["plan"]["per_source_limit"]`` 动态决定。
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any

from workflows.state import KBState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

GITHUB_SEARCH_URL: str = (
    "https://api.github.com/search/repositories?q=topic:ai+topic:agent&sort=stars"
)
"""GitHub Search API 查询地址（不含 per_page，由 plan 动态决定）。"""

DEFAULT_TIMEOUT: int = 15
"""网络请求超时（秒）。"""

DEFAULT_PER_SOURCE_LIMIT: int = 10
"""plan 未指定 per_source_limit 时的每源采集量兜底值。"""


# ---------------------------------------------------------------------------
# 节点定义
# ---------------------------------------------------------------------------


def collect_node(state: KBState) -> dict[str, Any]:
    """采集节点：调用 GitHub Search API 获取 AI 相关仓库。

    产出报告式摘要（``title``/``url``/``description``/``stars`` 等），
    不携带原始 API 全量响应。

    Args:
        state: 工作流共享状态。

    Returns:
        部分状态更新，仅包含 ``sources`` 字段。
    """
    logger.info("[Collector] 开始采集 GitHub AI 相关仓库")
    sources: list[dict[str, Any]] = []

    plan = state.get("plan") or {}
    per_source_limit = int(plan.get("per_source_limit", DEFAULT_PER_SOURCE_LIMIT))
    url = f"{GITHUB_SEARCH_URL}&per_page={per_source_limit}"

    headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            data: dict[str, object] = json.loads(resp.read().decode())

        items = data.get("items")
        if isinstance(items, list):
            for repo in items:
                if not isinstance(repo, dict):
                    continue
                sources.append(
                    {
                        "source": "github",
                        "title": repo.get("full_name", ""),
                        "url": repo.get("html_url", ""),
                        "description": repo.get("description", ""),
                        "stars": repo.get("stargazers_count", 0),
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
    except Exception as e:
        logger.error("[Collector] GitHub 采集失败: %s", e)
        sources.append({"source": "github", "title": "[ERROR]", "description": str(e)})

    logger.info("[Collector] 采集到 %d 条原始数据", len(sources))
    return {"sources": sources}
