"""工作流节点定义 — 5 个核心节点。

节点调用链::

    collect → analyze → organize → review → (conditional) → save
                                ↑                          │
                                └──────── organize (retry) ←┘

每个节点都是纯函数：接收 :class:`~workflows.state.KBState`，返回部分状态更新
（``dict``），由 LangGraph 自动合并进共享状态。各节点只负责自己的字段，实现
职责隔离。

依赖 :mod:`pipeline.model_client` 提供的 LLM 调用与用量累加接口：
``chat`` / ``chat_json`` / ``accumulate_usage``。
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from datetime import datetime, timezone
from typing import Any

from pipeline.model_client import accumulate_usage, chat_json
from workflows.state import KBState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

GITHUB_SEARCH_URL: str = (
    "https://api.github.com/search/repositories"
    "?q=topic:ai+topic:agent&sort=stars&per_page=10"
)
"""GitHub Search API 查询地址，按 stars 降序取 top 10 AI/Agent 仓库。"""

DEFAULT_TIMEOUT: int = 15
"""网络请求超时（秒）。"""

RELEVANCE_THRESHOLD: float = 0.6
"""相关度最低门槛，低于该值的条目在整理阶段被过滤。"""

MAX_REVIEW_ITERATIONS: int = 3
"""审核循环次数上限，达到上限时强制通过，避免死循环。"""

REVIEW_PASS_THRESHOLD: float = 3.5
"""审核总分及格线，``overall_score`` 达到该值即通过。"""

REVIEWER_SYSTEM: str = "你是严格但公正的知识库审核员。"
"""审核节点的系统提示词。"""

REVISION_TIMEOUT: float = 180.0
"""整理节点定向修正调用的超时（秒）。

修正 prompt 需一次性携带全部条目与审核反馈并重写 JSON 数组，输入输出都较大，
故使用比默认 60s 更长的超时，避免重写频繁超时。
"""

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

    headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        req = urllib.request.Request(GITHUB_SEARCH_URL, headers=headers)
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


def analyze_node(state: KBState) -> dict[str, Any]:
    """分析节点：用 LLM 对每条数据生成中文摘要、标签、评分。

    Args:
        state: 工作流共享状态。

    Returns:
        部分状态更新，包含 ``analyses`` 和累加后的 ``cost_tracker``。
    """
    logger.info("[Analyzer] 开始分析 %d 条数据", len(state["sources"]))
    analyses: list[dict[str, Any]] = []
    tracker = state["cost_tracker"]

    for item in state["sources"]:
        if str(item.get("title", "")).startswith("[ERROR]"):
            continue

        prompt = f"""请分析以下技术项目，用 JSON 格式返回：
项目名: {item.get("title", "")}
描述: {item.get("description", "无描述")}

返回格式: {{"summary": "200字中文摘要", "tags": ["标签"], "relevance_score": 0.8, "category": "分类", "key_insight": "一句话洞察"}}"""

        try:
            result, usage = chat_json(prompt)
            tracker = accumulate_usage(tracker, usage)
            analyses.append({**item, **result})
        except Exception as e:
            logger.error("[Analyzer] 分析失败: %s - %s", item.get("title"), e)
            analyses.append(
                {**item, "summary": f"分析失败: {e}", "relevance_score": 0.0}
            )

    logger.info("[Analyzer] 完成 %d 条分析", len(analyses))
    return {"analyses": analyses, "cost_tracker": tracker}


def organize_node(state: KBState) -> dict[str, Any]:
    """整理节点：过滤低分条目 + 按 URL 去重 + 如有反馈则定向修正。

    Args:
        state: 工作流共享状态。

    Returns:
        部分状态更新，包含 ``articles`` 和累加后的 ``cost_tracker``。
    """
    logger.info("[Organizer] 开始整理 %d 条分析结果", len(state["analyses"]))
    feedback = state["review_feedback"]
    iteration = state["iteration"]
    tracker = state["cost_tracker"]

    qualified = [
        a
        for a in state["analyses"]
        if _to_float(a.get("relevance_score", 0)) >= RELEVANCE_THRESHOLD
    ]

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in qualified:
        url = str(item.get("url", ""))
        if url and url not in seen:
            seen.add(url)
            unique.append(item)

    if feedback and iteration > 0:
        prompt = f"""你是知识库编辑。请根据以下审核反馈修正知识条目，只修正反馈指出的问题。

审核反馈:
{feedback}

待修正条目（JSON 数组）:
{json.dumps(unique, ensure_ascii=False, indent=2)}

要求：
1. 只返回修正后的 JSON 数组，不要 markdown 代码块、不要额外说明。
2. 保留每个条目的 source、url、description、stars、collected_at 等字段不变，
   仅修正 summary、tags、category、key_insight 中反馈指出的问题。
3. 未被反馈指出的条目原样返回。"""
        try:
            improved, usage = chat_json(prompt, timeout=REVISION_TIMEOUT)
            tracker = accumulate_usage(tracker, usage)
            if isinstance(improved, list):
                revised = [i for i in improved if isinstance(i, dict)]
                revised_by_url = {
                    str(i.get("url", "")): i for i in revised if i.get("url")
                }
                merged: list[dict[str, Any]] = []
                for item in unique:
                    rev = revised_by_url.get(str(item.get("url", "")))
                    merged.append({**item, **rev} if rev else item)
                unique = merged
        except Exception as e:
            logger.warning("[Organizer] 修正失败，保留原条目: %s", e)

    date_compact = datetime.now(timezone.utc).strftime("%Y%m%d")
    articles: list[dict[str, Any]] = [
        {
            "id": _make_article_id(item.get("source"), date_compact, i + 1),
            **{k: item.get(k, "") for k in ARTICLE_FIELDS},
        }
        for i, item in enumerate(unique)
    ]

    logger.info("[Organizer] 整理出 %d 条知识条目 (迭代 %d)", len(articles), iteration)
    return {"articles": articles, "cost_tracker": tracker}


def review_node(state: KBState) -> dict[str, Any]:
    """审核节点：LLM 四维度评分（摘要质量/标签准确/分类合理/一致性）。

    审核输出 JSON ``{"passed": bool, "overall_score": float, "feedback": str,
    "scores": {...}}``。达到最大审核次数时强制通过。

    Args:
        state: 工作流共享状态。

    Returns:
        部分状态更新，包含 ``review_passed``、``review_feedback``、
        递增后的 ``iteration`` 和累加后的 ``cost_tracker``。
    """
    logger.info("[Reviewer] 开始第 %d 次审核", state["iteration"] + 1)
    articles = state["articles"]
    iteration = state["iteration"]
    tracker = state["cost_tracker"]

    if not articles:
        logger.info("[Reviewer] 没有条目需要审核，直接通过")
        return {
            "review_passed": True,
            "review_feedback": "没有条目需要审核",
            "iteration": iteration + 1,
        }

    prompt = f"""你是知识库质量审核员。请审核以下条目：
{json.dumps(articles, ensure_ascii=False, indent=2)}

评分维度（1-5分）：摘要质量、标签准确性、分类合理性、整体一致性
overall_score >= {REVIEW_PASS_THRESHOLD} 即通过。第 {iteration + 1} 次审核（最多 {MAX_REVIEW_ITERATIONS} 次）。

返回 JSON: {{"passed": true/false, "overall_score": 4.2, "feedback": "改进建议", "scores": {{...}}}}"""

    try:
        result, usage = chat_json(prompt, system=REVIEWER_SYSTEM)
        tracker = accumulate_usage(tracker, usage)
        passed: bool = bool(result.get("passed", False))
        feedback: str = str(result.get("feedback", ""))

        if iteration >= MAX_REVIEW_ITERATIONS - 1:
            passed = True
            feedback += (
                f"\n[系统] 已达最大审核次数({MAX_REVIEW_ITERATIONS}次)，强制通过。"
            )

        logger.info(
            "[Reviewer] 得分: %s, 通过: %s (迭代 %d/%d)",
            result.get("overall_score", "?"),
            passed,
            iteration + 1,
            MAX_REVIEW_ITERATIONS,
        )
    except Exception as e:
        logger.error("[Reviewer] 审核失败: %s，自动通过", e)
        passed = True
        feedback = f"审核失败: {e}，自动通过"

    return {
        "review_passed": passed,
        "review_feedback": feedback,
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }


def save_node(state: KBState) -> dict[str, Any]:
    """保存节点：将 ``articles`` 写入 ``knowledge/articles/`` 并更新索引。

    每篇文章写为 ``{id}.json``，同时维护 ``index.json`` 索引文件
    （记录 ``id``/``title``/``category``，按 ``id`` 去重追加）。

    Args:
        state: 工作流共享状态。

    Returns:
        空的部分状态更新（本节点不修改任何状态字段）。
    """
    logger.info("[Saver] 准备保存 %d 篇文章", len(state["articles"]))
    articles = state["articles"]
    if not articles:
        logger.info("[Saver] 没有条目需要保存")
        return {}

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
            logger.warning("[Saver] 索引读取失败，重建: %s", e)

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

    logger.info("[Saver] 保存 %d 篇文章", len(articles))
    return {}
