"""Organizer 节点（终态）— 过滤 + 去重（含历史）+ 格式化 + 落盘。

定向修正由独立的 ``revise_node`` 负责；organize 产出 ``articles`` 并写入
``knowledge/articles/``（含 ``index.json``）。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from core.utils import load_existing_urls, make_article_id, slugify
from safeguards.security import filter_output
from workflows.state import KBState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_MIN_INNOVATION_SCORE: int = 2
"""plan 未指定 min_innovation_score 时的创新分过滤阈值兜底值。"""

MASKED_TEXT_FIELDS: tuple[str, ...] = ("summary", "description")
"""落盘前需做 PII 掩码的文本字段。

``summary`` 为 LLM 输出，``description`` 为外部原文，两者都会写入
``knowledge/articles/`` 并可能被推送分发，统一在写盘前掩码。
"""

MASKED_LIST_FIELDS: tuple[str, ...] = ("key_points", "risks")
"""落盘前需逐项做 PII 掩码的字符串列表字段（均为 LLM 输出）。"""


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


def _mask_pii(articles: list[dict[str, Any]]) -> int:
    """写盘前对 articles 的文本字段做 PII 检测与掩码（原地修改）。

    LLM 输出（或外部描述原文）一旦夹带真实手机号/邮箱/身份证，随文件落盘
    并推送 GitHub 即永久泄露，因此掩码必须发生在 ``_save_articles`` 之前。

    Args:
        articles: 待落盘的知识条目列表（原地掩码）。

    Returns:
        检出并掩码的 PII 处数。
    """
    hits = 0
    for article in articles:
        for key in MASKED_TEXT_FIELDS:
            value = str(article.get(key, "") or "")
            filtered, detections = filter_output(value)
            if detections:
                hits += len(detections)
                logger.warning(
                    "[Organizer] PII 掩码 (%s %s): %s",
                    article.get("id", ""),
                    key,
                    detections,
                )
                article[key] = filtered
        for key in MASKED_LIST_FIELDS:
            items = article.get(key, [])
            if not isinstance(items, list):
                continue
            masked_items: list[str] = []
            for entry in items:
                filtered, detections = filter_output(str(entry))
                if detections:
                    hits += len(detections)
                    logger.warning(
                        "[Organizer] PII 掩码 (%s %s[]): %s",
                        article.get("id", ""),
                        key,
                        detections,
                    )
                masked_items.append(filtered)
            article[key] = masked_items
    return hits


# ---------------------------------------------------------------------------
# 节点定义
# ---------------------------------------------------------------------------


def organize_node(state: KBState) -> dict[str, Any]:
    """整理节点（终态）：过滤 + 去重（含历史）+ 格式化 + 落盘。

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
    min_innovation_score = int(
        plan.get("min_innovation_score", DEFAULT_MIN_INNOVATION_SCORE)
    )

    qualified = [
        a
        for a in state["analyses"]
        if _to_float(a.get("innovation_score", 0)) >= min_innovation_score
    ]

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    articles_dir = os.path.join(base_dir, "knowledge", "articles")
    seen = load_existing_urls(articles_dir)
    unique: list[dict[str, Any]] = []
    for item in qualified:
        url = str(item.get("url", ""))
        if url and url not in seen:
            seen.add(url)
            unique.append(item)

    date_compact = datetime.now(timezone.utc).strftime("%Y%m%d")
    analyzed_at = datetime.now(timezone.utc).isoformat()
    articles: list[dict[str, Any]] = []
    for i, item in enumerate(unique):
        articles.append(
            {
                "id": make_article_id(item.get("source"), date_compact, i + 1),
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "source_url": item.get("url", ""),
                "description": item.get("description", ""),
                "summary": item.get("summary", ""),
                "tags": item.get("tags", []),
                "category": item.get("category", ""),
                "status": "draft",
                "stars": item.get("stars"),
                "collected_at": item.get("collected_at", ""),
                "raw_path": item.get("raw_path", ""),
                "analyzed_at": analyzed_at,
                "published_at": None,
                "innovation_score": item.get("innovation_score"),
                "difficulty_score": item.get("difficulty_score"),
                "key_points": item.get("key_points", []),
                "risks": item.get("risks", []),
            }
        )

    # 写盘前最后一道防线：PII 检测与掩码
    pii_hits = _mask_pii(articles)
    if pii_hits:
        logger.warning("[Organizer] 写盘前共掩码 %d 处 PII", pii_hits)

    _save_articles(articles)
    logger.info(
        "[Organizer] 整理并保存 %d 条知识条目 (迭代 %d)", len(articles), iteration
    )
    return {"articles": articles}


def _save_articles(articles: list[dict[str, Any]]) -> None:
    """将知识条目写入 ``knowledge/articles/`` 并更新 ``index.json``。

    每篇文章写为 ``{date}-{source}-{slug}.json``（与 V2/Agent 命名一致），
    同时维护 ``index.json``（记录 id/title/category，按 id 去重追加）。

    Args:
        articles: 已格式化的知识条目列表。
    """
    if not articles:
        logger.info("[Organizer] 没有条目需要保存")
        return

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    articles_dir = os.path.join(base_dir, "knowledge", "articles")
    os.makedirs(articles_dir, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for article in articles:
        title = article.get("title", "")
        slug = slugify(str(title)) if title else "unknown"
        slug = slug or "unknown"
        source = str(article.get("source", "unknown")).replace("/", "_")
        filename = f"{date_str}-{source}-{slug}.json"
        filepath = os.path.join(articles_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(article, f, ensure_ascii=False, indent=2)

    index_path = os.path.join(base_dir, "knowledge", "index.json")
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
