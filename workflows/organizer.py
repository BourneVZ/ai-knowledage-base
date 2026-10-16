"""Organizer 节点（终态）— 过滤 + 去重 + 格式化 + 落盘。

定向修正由独立的 ``revise_node`` 负责；organize 产出 ``articles`` 并写入
``knowledge/articles/``（含 ``index.json``）。
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from workflows.state import KBState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_RELEVANCE_THRESHOLD: float = 0.5
"""plan 未指定 relevance_threshold 时的过滤阈值兜底值。"""

ARTICLE_FIELDS: tuple[str, ...] = (
    "title",
    "source",
    "url",
    "summary",
    "tags",
    "relevance_score",
    "category",
    "key_insight",
)
"""知识条目标准字段，整理阶段仅保留这些字段输出。"""


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _to_float(value: object) -> float:
    """安全地将任意值转换为 ``float``，失败时返回 0.0。

    Args:
        value: 待转换值（可能是 ``str``、``int``、``float`` 或 ``None``）。

    Returns:
        转换后的浮点数。
    """
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _make_article_id(source: object, date_compact: str, index: int) -> str:
    """生成符合项目规范的条目 ID（``{source}-{YYYYMMDD}-{NNN}``）。

    来源段仅保留小写字母与下划线（匹配 ``hooks/validate_json.py`` 的
    ``ID_PATTERN`` ``^[a-z_]+-\\d{8}-\\d{3}$``），``rss/xxx`` 会归一为 ``xxx``。

    Args:
        source: 数据来源值（如 ``"github"``、``"rss/hn"``）。
        date_compact: ``YYYYMMDD`` 格式日期。
        index: 序号（从 1 开始，零填充为 3 位）。

    Returns:
        格式为 ``{source}-{YYYYMMDD}-{NNN}`` 的 ID。
    """
    segment = re.sub(r"[^a-z_]", "", str(source or "").lower().replace("rss/", ""))
    if not segment:
        segment = "unknown"
    return f"{segment}-{date_compact}-{index:03d}"


# ---------------------------------------------------------------------------
# 节点定义
# ---------------------------------------------------------------------------


def organize_node(state: KBState) -> dict[str, Any]:
    """整理节点（终态）：过滤 + 去重 + 格式化 + 落盘。

    定向修正由独立的 ``revise_node`` 负责；organize 产出 ``articles`` 并写入
    ``knowledge/articles/``（含 ``index.json``）。

    Args:
        state: 工作流共享状态。

    Returns:
        部分状态更新，仅包含 ``articles`` 字段。
    """
    logger.info("[Organizer] 开始整理 %d 条分析结果", len(state["analyses"]))
    iteration = state["iteration"]

    plan = state.get("plan") or {}
    relevance_threshold = _to_float(
        plan.get("relevance_threshold", DEFAULT_RELEVANCE_THRESHOLD)
    )

    qualified = [
        a
        for a in state["analyses"]
        if _to_float(a.get("relevance_score", 0)) >= relevance_threshold
    ]

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in qualified:
        url = str(item.get("url", ""))
        if url and url not in seen:
            seen.add(url)
            unique.append(item)

    date_compact = datetime.now(timezone.utc).strftime("%Y%m%d")
    articles: list[dict[str, Any]] = [
        {
            "id": _make_article_id(item.get("source"), date_compact, i + 1),
            **{k: item.get(k, "") for k in ARTICLE_FIELDS},
        }
        for i, item in enumerate(unique)
    ]

    _save_articles(articles)
    logger.info(
        "[Organizer] 整理并保存 %d 条知识条目 (迭代 %d)", len(articles), iteration
    )
    return {"articles": articles}


def _save_articles(articles: list[dict[str, Any]]) -> None:
    """将知识条目写入 ``knowledge/articles/`` 并更新 ``index.json``。

    每篇文章写为 ``{id}.json``，同时维护 ``index.json``（记录 id/title/category，
    按 id 去重追加）。

    Args:
        articles: 已格式化的知识条目列表。
    """
    if not articles:
        logger.info("[Organizer] 没有条目需要保存")
        return

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    articles_dir = os.path.join(base_dir, "knowledge", "articles")
    os.makedirs(articles_dir, exist_ok=True)

    for article in articles:
        aid = article.get("id")
        if not isinstance(aid, str) or not aid:
            continue
        filepath = os.path.join(articles_dir, f"{aid}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(article, f, ensure_ascii=False, indent=2)

    index_path = os.path.join(articles_dir, "index.json")
    index: list[dict[str, Any]] = []
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                index = loaded
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("[Organizer] 索引读取失败，重建: %s", e)

    existing_ids = {e.get("id") for e in index if isinstance(e, dict)}
    for article in articles:
        aid = article.get("id")
        if aid not in existing_ids:
            index.append(
                {
                    "id": aid,
                    "title": article.get("title", ""),
                    "category": article.get("category", ""),
                }
            )
            existing_ids.add(aid)

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    logger.info("[Organizer] 保存 %d 篇文章", len(articles))
