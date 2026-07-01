#!/usr/bin/env python3
"""AI 知识库自动化流水线 — 四步管道执行脚本。

Step 1: 采集（Collect）— 从 GitHub Search API 和 RSS 源采集 AI 相关内容
Step 2: 分析（Analyze）— 调用 LLM 对每条内容进行摘要/评分/标签分析
Step 3: 整理（Organize）— 去重 + 格式标准化 + 校验
Step 4: 保存（Save）— 将文章保存为独立 JSON 文件到 knowledge/articles/

用法::

    python pipeline/pipeline.py --sources github,rss --limit 20
    python pipeline/pipeline.py --sources github --limit 5
    python pipeline/pipeline.py --sources rss --limit 10
    python pipeline/pipeline.py --sources github --limit 5 --dry-run
    python pipeline/pipeline.py --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypedDict

import httpx

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    yaml = None  # type: ignore[assignment]

try:
    from .model_client import chat_with_retry  # type: ignore[assignment]
except ImportError:
    from model_client import chat_with_retry  # type: ignore[no-redef]

try:
    from .model_client import create_provider  # type: ignore[assignment]
except ImportError:
    from model_client import create_provider  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
RAW_DIR: Path = PROJECT_ROOT / "knowledge" / "raw"
ARTICLES_DIR: Path = PROJECT_ROOT / "knowledge" / "articles"
DEFAULT_TIMEOUT: float = 30.0
MAX_RETRIES: int = 3
GITHUB_API_BASE: str = "https://api.github.com"
GITHUB_SEARCH_QUERY: str = "ai agent llm in:name,description"

RSS_SOURCES: dict[str, str] = {
    "hn": "https://hnrss.org/newest?q=ai+OR+llm+OR+agent+OR+machine+learning",
    "arxiv": "https://rss.arxiv.org/rss/cs.AI",
}

DEFAULT_RSS_CONFIG: Path = Path(__file__).resolve().parent / "rss_sources.yaml"


def _load_rss_config(yaml_path: Path | None = None) -> dict[str, str]:
    """从 YAML 配置文件加载启用的 RSS 源。

    若 PyYAML 未安装或文件缺失，回退到硬编码默认值。

    Args:
        yaml_path: YAML 配置文件路径，为 ``None`` 时使用默认路径。

    Returns:
        RSS 源名称到 URL 的映射。
    """
    if yaml is None:
        logger.info("PyYAML 未安装，使用内置默认 RSS 源")
        return dict(RSS_SOURCES)

    path = yaml_path or DEFAULT_RSS_CONFIG
    if not path.is_file():
        logger.warning("RSS 配置文件 %s 不存在，使用内置默认 RSS 源", path)
        return dict(RSS_SOURCES)

    try:
        with path.open("r", encoding="utf-8") as f:
            data: dict[str, object] = yaml.safe_load(f)
    except Exception as e:
        logger.warning("RSS 配置文件解析失败: %s，使用内置默认 RSS 源", e)
        return dict(RSS_SOURCES)

    if not isinstance(data, dict):
        logger.warning("RSS 配置文件格式错误，使用内置默认 RSS 源")
        return dict(RSS_SOURCES)

    raw_sources: object = data.get("sources")
    if not isinstance(raw_sources, list):
        logger.warning("RSS 配置缺少 sources 列表，使用内置默认 RSS 源")
        return dict(RSS_SOURCES)

    enabled: dict[str, str] = {}
    for src in raw_sources:
        if not isinstance(src, dict):
            continue
        if not src.get("enabled", False):
            continue
        name: object = src.get("name")
        url: object = src.get("url")
        if isinstance(name, str) and isinstance(url, str) and name and url:
            enabled[name] = url

    if not enabled:
        logger.warning("RSS 配置中没有启用的源，使用内置默认 RSS 源")
        return dict(RSS_SOURCES)

    logger.info("从 %s 加载了 %d 个 RSS 源", path, len(enabled))
    for name, url in enabled.items():
        logger.debug("  %s → %s", name, url)
    return enabled

VALID_SOURCES: frozenset[str] = frozenset({"github", "rss", "hn", "arxiv"})
VALID_STATUSES: frozenset[str] = frozenset(
    {"draft", "needs_review", "approved", "published", "rejected"}
)
VALID_CATEGORIES: frozenset[str] = frozenset(
    {
        "LLM Framework",
        "AI Agent",
        "Inference Engine",
        "Vector Database",
        "Prompt Engineering",
        "AI Application",
        "AI Infrastructure",
        "AI Safety",
        "Research",
        "Developer Tools",
    }
)

REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "title",
        "source",
        "source_url",
        "summary",
        "tags",
        "category",
        "status",
        "collected_at",
        "raw_path",
    }
)

SUMMARY_MIN_LENGTH: int = 20
URL_PATTERN: re.Pattern[str] = re.compile(r"^https?://\S+$")


# ---------------------------------------------------------------------------
# 数据类型
# ---------------------------------------------------------------------------


class CollectedItem(TypedDict):
    """采集阶段产出的单条原始数据。"""

    title: str
    url: str
    source: str
    description: str
    metadata: dict[str, Any]
    collected_at: str


class AnalyzedItem(TypedDict, total=False):
    """分析阶段产出的结构化条目（部分字段可能缺失）。"""

    id: str
    title: str
    source: str
    source_url: str
    description: str
    summary: str
    tags: list[str]
    category: str
    status: str
    language: str
    stars: int | None
    authors: list[str]
    collected_at: str
    analyzed_at: str
    published_at: str | None
    innovation_score: int | None
    difficulty_score: int | None
    key_points: list[str]
    risks: list[str]
    raw_path: str
    metadata: dict[str, Any]


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """将文本转换为文件名安全的小写 slug。

    Args:
        text: 原始文本（如仓库名、标题）。

    Returns:
        仅含小写字母、数字和连字符的 slug。
    """
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


def _make_article_id(source: str, date_str: str, index: int) -> str:
    """生成符合规范的知识条目 ID。

    Args:
        source: 数据来源（如 ``github``、``rss``）。
        date_str: 日期字符串（``YYYYMMDD`` 格式）。
        index: 序号（从 1 开始的 3 位零填充）。

    Returns:
        格式为 ``{source}-{YYYYMMDD}-{NNN}`` 的 ID。
    """
    return f"{source}-{date_str}-{index:03d}"


def _now_iso() -> str:
    """获取当前东八区时间戳（ISO 8601 格式）。

    Returns:
        格式为 ``YYYY-MM-DDTHH:MM:SS+08:00`` 的时间戳。
    """
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def _today_str() -> str:
    """获取当前日期字符串（``YYYY-MM-DD`` 格式）。

    Returns:
        格式为 ``YYYY-MM-DD`` 的日期。
    """
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def _today_str_compact() -> str:
    """获取当前日期字符串（``YYYYMMDD`` 格式）。

    Returns:
        格式为 ``YYYYMMDD`` 的日期。
    """
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")


def _load_existing_urls(articles_dir: Path) -> set[str]:
    """扫描已有文章目录，提取所有 ``source_url`` 用于去重。

    Args:
        articles_dir: 知识条目目录路径。

    Returns:
        已存在的 ``source_url`` 集合。
    """
    existing: set[str] = set()
    if not articles_dir.is_dir():
        return existing
    for fpath in articles_dir.glob("*.json"):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            url = data.get("source_url", "")
            if isinstance(url, str) and url:
                existing.add(url)
        except (json.JSONDecodeError, OSError):
            logger.warning("跳过无法解析的已有文章: %s", fpath)
    return existing


# ---------------------------------------------------------------------------
# HTTP 请求辅助
# ---------------------------------------------------------------------------


def _http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, object] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = MAX_RETRIES,
) -> str:
    """带重试的 HTTP GET 请求。

    Args:
        url: 请求地址。
        headers: 请求头字典。
        params: 查询参数字典。
        timeout: 超时时间（秒）。
        max_retries: 最大重试次数（不含首次请求）。

    Returns:
        响应文本内容。

    Raises:
        httpx.HTTPError: 全部尝试失败。
    """
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                return resp.text
        except httpx.TimeoutException as e:
            last_error = e
            logger.warning(
                "请求超时 (attempt %d/%d): url=%s, err=%s",
                attempt + 1,
                max_retries + 1,
                url,
                e,
            )
        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code < 500:
                logger.error(
                    "客户端错误 %d (attempt %d/%d)，不重试: url=%s",
                    e.response.status_code,
                    attempt + 1,
                    max_retries + 1,
                    url,
                )
                raise
            logger.warning(
                "服务端错误 %d (attempt %d/%d): url=%s",
                e.response.status_code,
                attempt + 1,
                max_retries + 1,
                url,
            )
        except httpx.HTTPError as e:
            last_error = e
            logger.warning(
                "网络错误 (attempt %d/%d): url=%s, err=%s",
                attempt + 1,
                max_retries + 1,
                url,
                e,
            )

        if attempt < max_retries:
            delay = min(1.0 * (2**attempt), 30.0)
            logger.info("等待 %.1f 秒后重试...", delay)
            import time as _time

            _time.sleep(delay)

    raise last_error  # type: ignore[misc]


# ===================================================================
# Step 1: 采集
# ===================================================================


def collect_github(
    limit: int = 20,
    github_token: str | None = None,
) -> list[CollectedItem]:
    """从 GitHub Search API 采集 AI 相关仓库。

    Args:
        limit: 最大返回条数（最大 100）。
        github_token: 可选 GitHub 个人访问令牌，提高速率限制。

    Returns:
        ``CollectedItem`` 列表。
    """
    url = f"{GITHUB_API_BASE}/search/repositories"
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-knowledge-base/1.0",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    params: dict[str, str | int] = {
        "q": GITHUB_SEARCH_QUERY,
        "sort": "stars",
        "order": "desc",
        "per_page": min(limit, 100),
    }

    logger.info("采集 GitHub: q=%s, per_page=%d", GITHUB_SEARCH_QUERY, params["per_page"])
    try:
        resp_text = _http_get(url, headers=headers, params=params)
    except httpx.HTTPError as e:
        logger.error("GitHub 搜索请求失败: %s", e)
        return []

    try:
        data: dict[str, object] = json.loads(resp_text)
    except json.JSONDecodeError as e:
        logger.error("GitHub 搜索响应 JSON 解析失败: %s", e)
        return []

    items_raw: object = data.get("items")
    if not isinstance(items_raw, list):
        logger.error("GitHub 搜索响应中无 items 字段")
        return []

    collected_at = _now_iso()
    results: list[CollectedItem] = []
    for item in items_raw:
        if not isinstance(item, dict):
            continue
        full_name: object = item.get("full_name", "")
        html_url: object = item.get("html_url", "")
        description: object = item.get("description", "")
        language: object = item.get("language")
        stars: object = item.get("stargazers_count", 0)
        topics: object = item.get("topics", [])
        owner_obj: object = item.get("owner", {})
        owner_name = ""
        if isinstance(owner_obj, dict):
            owner_name = str(owner_obj.get("login", ""))

        if not isinstance(full_name, str) or not full_name:
            continue
        if not isinstance(html_url, str) or not html_url:
            continue

        results.append(
            CollectedItem(
                title=full_name,
                url=html_url,
                source="github",
                description=str(description) if description else "",
                metadata={
                    "stars": int(stars) if isinstance(stars, (int, float)) else 0,
                    "language": str(language) if language else "",
                    "topics": list(topics) if isinstance(topics, list) else [],
                    "owner": owner_name,
                },
                collected_at=collected_at,
            )
        )

    logger.info("GitHub 采集完成，命中 %d 条", len(results))
    return results


def collect_rss(
    sources: dict[str, str] | None = None,
    limit: int = 20,
) -> list[CollectedItem]:
    """从 RSS 源采集 AI 相关内容。

    使用简易正则解析 RSS XML，不依赖 feedparser。

    Args:
        sources: RSS 源名称到 URL 的映射，默认为 :data:`RSS_SOURCES`。
        limit: 每个源的最大返回条数。

    Returns:
        ``CollectedItem`` 列表。
    """
    if sources is None:
        sources = RSS_SOURCES

    collected_at = _now_iso()
    results: list[CollectedItem] = []

    for name, feed_url in sources.items():
        logger.info("采集 RSS: name=%s, url=%s", name, feed_url)
        try:
            resp_text = _http_get(feed_url)
        except httpx.HTTPError as e:
            logger.error("RSS 源 %s 请求失败: %s", name, e)
            continue

        items = _parse_rss_items(resp_text)
        logger.info("RSS %s 解析出 %d 条条目", name, len(items))

        for idx, item in enumerate(items):
            if idx >= limit:
                break
            title = item.get("title", "")
            link = item.get("link", "")
            description = item.get("description", "")
            if not title or not link:
                continue
            results.append(
                CollectedItem(
                    title=title,
                    url=link,
                    source=f"rss/{name}",
                    description=_strip_html(description),
                    metadata={
                        "rss_source": name,
                        "pub_date": item.get("pub_date", ""),
                    },
                    collected_at=collected_at,
                )
            )

    logger.info("RSS 采集完成，共 %d 条", len(results))
    return results


def _parse_rss_items(xml_text: str) -> list[dict[str, str]]:
    """使用正则从 RSS XML 中提取所有 ``<item>`` 标签内容。

    不依赖 XML 库，针对 RSS 2.0 常见结构做容错解析。

    Args:
        xml_text: RSS 2.0 XML 原始文本。

    Returns:
        解析后的条目列表，每项含 ``title``、``link``、``description``、``pub_date``。
    """
    items: list[dict[str, str]] = []
    item_blocks = re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL)
    for block in item_blocks:
        title_match = re.search(r"<title>(.*?)</title>", block, re.DOTALL)
        link_match = re.search(r"<link>(.*?)</link>", block, re.DOTALL)
        desc_match = re.search(
            r"<description>(.*?)</description>", block, re.DOTALL
        )
        pub_match = re.search(r"<pubDate>(.*?)</pubDate>", block, re.DOTALL)
        items.append(
            {
                "title": _decode_xml(title_match.group(1).strip()) if title_match else "",
                "link": link_match.group(1).strip() if link_match else "",
                "description": _decode_xml(desc_match.group(1).strip()) if desc_match else "",
                "pub_date": pub_match.group(1).strip() if pub_match else "",
            }
        )
    return items


def _decode_xml(text: str) -> str:
    """简易 XML 实体解码。

    仅处理 ``<![CDATA[...]]>`` 块和常见 XML 实体。

    Args:
        text: 可能包含 XML 实体或 CDATA 的文本。

    Returns:
        解码后的纯文本。
    """
    cdata_match = re.match(r"<!\[CDATA\[(.*?)\]\]>", text, re.DOTALL)
    if cdata_match:
        text = cdata_match.group(1)
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&amp;", "&").replace("&quot;", '"').replace("&apos;", "'")
    return text


def _strip_html(text: str) -> str:
    """简易去除 HTML 标签。

    Args:
        text: 可能含 HTML 的文本。

    Returns:
        去除标签后的纯文本。
    """
    return re.sub(r"<[^>]*>", "", text).strip()


# ===================================================================
# Step 2: 分析
# ===================================================================


ANALYZE_SYSTEM_PROMPT: str = """你是一个 AI 技术内容分析专家。请对以下技术内容进行分析，输出严格的 JSON。

## 分析要求
1. **summary**: 用中文写一个 80-200 字的简明摘要，概括核心功能和技术亮点。
2. **tags**: 提取 3-5 个英文技术标签（小写，如 ai、llm、agent、open-source）。
3. **category**: 从以下分类中选择一个最匹配的：
   - LLM Framework
   - AI Agent
   - Inference Engine
   - Vector Database
   - Prompt Engineering
   - AI Application
   - AI Infrastructure
   - AI Safety
   - Research
   - Developer Tools
4. **innovation_score**: 创新程度评分 1-5（整数），5 表示颠覆性创新。
5. **difficulty_score**: 使用/复现难度评分 1-5（整数），5 表示需要深厚专业背景。
6. **key_points**: 提炼 2-3 个核心亮点（中文短语列表）。
7. **risks**: 1-2 个潜在局限或不确定性（中文短语列表，如无则空数组）。

## 输出格式
仅输出 JSON 对象，不要包含 markdown 标记或额外文本：
{{
    "summary": "...",
    "tags": ["ai", "llm"],
    "category": "AI Agent",
    "innovation_score": 4,
    "difficulty_score": 3,
    "key_points": ["亮点1", "亮点2"],
    "risks": ["风险1"]
}}

## 待分析内容
标题: {title}
描述: {description}
来源: {source}
元数据: {metadata}
"""


def analyze_items(
    items: list[CollectedItem],
    dry_run: bool = False,
) -> list[AnalyzedItem]:
    """调用 LLM 对采集到的每条内容进行摘要/评分/标签分析。

    Args:
        items: 采集阶段产出的原始数据列表。
        dry_run: 干跑模式，跳过 LLM 调用并填充占位数据。

    Returns:
        分析后的 ``AnalyzedItem`` 列表。
    """
    if dry_run:
        logger.info("dry-run 模式：跳过 LLM 分析，填充占位数据")
        return [_analyze_placeholder(item) for item in items]

    results: list[AnalyzedItem] = []
    date_compact = _today_str_compact()

    for idx, item in enumerate(items):
        source = item["source"]
        base_source = source.replace("rss/", "")

        logger.info(
            "分析中 [%d/%d]: %s (%s)",
            idx + 1,
            len(items),
            item["title"],
            source,
        )

        try:
            analysis = _call_llm_analyze(item)
        except Exception as e:
            logger.error("LLM 分析失败: %s — %s", item["title"], e)
            results.append(_analyze_placeholder(item))
            continue

        results.append(
            AnalyzedItem(
                id=_make_article_id(base_source, date_compact, idx + 1),
                title=item["title"],
                source=source,
                source_url=item["url"],
                description=item["description"],
                summary=analysis.get("summary", item["description"])[:200],
                tags=analysis.get("tags", ["ai"]),
                category=_sanitize_category(analysis.get("category", "AI Application")),
                status="draft",
                language=str(item.get("metadata", {}).get("language", "")),
                stars=item.get("metadata", {}).get("stars"),
                authors=[item.get("metadata", {}).get("owner", "")],
                collected_at=item["collected_at"],
                analyzed_at=_now_iso(),
                published_at=None,
                innovation_score=_safe_int_in_range(analysis.get("innovation_score"), 1, 5),
                difficulty_score=_safe_int_in_range(analysis.get("difficulty_score"), 1, 5),
                key_points=analysis.get("key_points", [])[:5],
                risks=analysis.get("risks", [])[:5],
                raw_path="",  # 将在整理阶段填充
                metadata=item.get("metadata", {}),
            )
        )

    logger.info("分析完成，共 %d 条", len(results))
    return results


def _call_llm_analyze(item: CollectedItem) -> dict[str, Any]:
    """调用 :func:`chat_with_retry` 分析单条内容。

    Args:
        item: 待分析条目。

    Returns:
        从 LLM 响应中解析出的分析结果字典。
    """
    metadata_str = json.dumps(item.get("metadata", {}), ensure_ascii=False)
    prompt = ANALYZE_SYSTEM_PROMPT.format(
        title=item["title"],
        description=item.get("description", ""),
        source=item["source"],
        metadata=metadata_str,
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": "你是一个输出严格 JSON 的 AI 内容分析专家。"},
        {"role": "user", "content": prompt},
    ]

    response = chat_with_retry(messages, temperature=0.3, max_tokens=1024)
    text = response.content.strip()

    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            logger.warning("LLM 返回的 JSON 解析失败，返回占位数据")

    return {
        "summary": item.get("description", ""),
        "tags": ["ai"],
        "category": "AI Application",
        "innovation_score": 3,
        "difficulty_score": 3,
        "key_points": [],
        "risks": [],
    }


def _analyze_placeholder(item: CollectedItem) -> AnalyzedItem:
    """为采集条目生成无 LLM 分析的占位数据。

    Args:
        item: 采集阶段条目。

    Returns:
        使用占位值的 ``AnalyzedItem``。
    """
    date_compact = _today_str_compact()
    base_source = item["source"].replace("rss/", "")
    return AnalyzedItem(
        id=_make_article_id(base_source, date_compact, 0),
        title=item["title"],
        source=item["source"],
        source_url=item["url"],
        description=item["description"],
        summary=item["description"],
        tags=["ai", "placeholder"],
        category="AI Application",
        status="draft",
        language=str(item.get("metadata", {}).get("language", "")),
        stars=item.get("metadata", {}).get("stars"),
        authors=[item.get("metadata", {}).get("owner", "")],
        collected_at=item["collected_at"],
        analyzed_at=_now_iso(),
        published_at=None,
        innovation_score=None,
        difficulty_score=None,
        key_points=[],
        risks=[],
        raw_path="",
        metadata=item.get("metadata", {}),
    )


def _sanitize_category(category: str) -> str:
    """校验分类是否在合法取值范围内，否则返回默认值。

    Args:
        category: 候选分类字符串。

    Returns:
        合法分类或默认值 ``"AI Application"``。
    """
    if category in VALID_CATEGORIES:
        return category
    logger.warning("未知分类 '%s'，使用默认值 'AI Application'", category)
    return "AI Application"


def _safe_int_in_range(value: object, lo: int, hi: int) -> int | None:
    """安全转换值为 [lo, hi] 范围内的整数，失败返回 None。

    Args:
        value: 待转换值。
        lo: 下限（含）。
        hi: 上限（含）。

    Returns:
        有效整数或 None。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        iv = int(value)
    except (ValueError, TypeError):
        return None
    if lo <= iv <= hi:
        return iv
    return None


# ===================================================================
# Step 3: 整理
# ===================================================================


def organize_items(
    items: list[AnalyzedItem],
    raw_path: str,
    articles_dir: Path,
) -> list[AnalyzedItem]:
    """去重 + 格式标准化 + 字段补全。

    - 按 ``source_url`` 去重（包括已有文章目录中的历史 URL）。
    - 为每条条目补全 ``raw_path``。
    - 确保 all required fields present。
    - 过滤缺少必填字段的条目。

    Args:
        items: 分析阶段产出的条目列表。
        raw_path: 原始数据文件相对路径。
        articles_dir: 知识条目目录，用于扫描已有 URL 去重。

    Returns:
        整理后的条目列表。
    """
    seen_urls = _load_existing_urls(articles_dir)
    deduped: list[AnalyzedItem] = []
    skipped = 0

    for item in items:
        url = item.get("source_url", "")
        if url in seen_urls:
            skipped += 1
            logger.debug("去重跳过: %s", url)
            continue
        seen_urls.add(url)

        item["raw_path"] = raw_path

        if not _validate_item_requirements(item):
            skipped += 1
            continue

        deduped.append(item)

    logger.info(
        "整理完成: 输入 %d, 去重/过滤 %d, 保留 %d",
        len(items),
        skipped,
        len(deduped),
    )
    return deduped


def _validate_item_requirements(item: AnalyzedItem) -> bool:
    """校验条目是否包含所有必填字段且值类型合法。

    Args:
        item: 待校验条目。

    Returns:
        通过校验返回 ``True``，否则返回 ``False``。
    """
    for field in REQUIRED_FIELDS:
        if field not in item:
            logger.warning("条目缺少必填字段 '%s': %s", field, item.get("title", "?"))
            return False

    if not isinstance(item.get("summary"), str) or len(item["summary"]) < SUMMARY_MIN_LENGTH:
        logger.warning("摘要过短或无效: %s", item.get("title", "?"))
        return False

    if not isinstance(item.get("tags"), list) or len(item["tags"]) < 1:
        logger.warning("标签为空: %s", item.get("title", "?"))
        return False

    source_url = item.get("source_url", "")
    if not isinstance(source_url, str) or not URL_PATTERN.match(source_url):
        logger.warning("source_url 无效: %s — %s", item.get("title", "?"), source_url)
        return False

    if item.get("status") not in VALID_STATUSES:
        logger.warning("状态值无效: %s", item.get("status"))
        item["status"] = "draft"

    return True


# ===================================================================
# Step 4: 保存
# ===================================================================


def save_items(
    items: list[AnalyzedItem],
    collected_items: list[CollectedItem],
    *,
    dry_run: bool = False,
) -> None:
    """将条目保存为独立 JSON 文件到 ``knowledge/articles/``。

    同时将原始采集数据保存到 ``knowledge/raw/``。

    Args:
        items: 整理后的条目列表。
        collected_items: 原始采集数据列表。
        dry_run: 干跑模式，仅打印不写入。
    """
    if dry_run:
        logger.info("=== dry-run: 以下内容将被保存 ===")
        for item in items:
            print(f"  [{item.get('source')}] {item.get('title')}")
        logger.info("=== dry-run 结束（共 %d 条，未写入） ===", len(items))
        return

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    date_str = _today_str()
    date_compact = _today_str_compact()

    if collected_items:
        raw_file = RAW_DIR / f"github-trending-{date_str}.json"
        raw_file.write_text(
            json.dumps(collected_items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("原始数据已保存: %s (%d 条)", raw_file, len(collected_items))

    saved = 0
    for item in items:
        title = item.get("title", "unknown")
        slug = _slugify(title) if title else "unknown"
        source = item.get("source", "unknown").replace("/", "_")
        filename = f"{date_str}-{source}-{slug}.json"
        filepath = ARTICLES_DIR / filename

        if filepath.exists():
            logger.warning("文件已存在，跳过: %s", filename)
            continue

        filepath.write_text(
            json.dumps(item, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        item["raw_path"] = str(
            RAW_DIR / f"github-trending-{date_str}.json"
        )
        saved += 1

    logger.info("文章已保存: %d 条 → %s", saved, ARTICLES_DIR)


# ===================================================================
# 流水线主逻辑
# ===================================================================


def run_pipeline(
    sources: list[str],
    limit: int = 20,
    *,
    dry_run: bool = False,
    github_token: str | None = None,
    rss_config: Path | None = None,
) -> None:
    """执行四步知识库自动化流水线。

    Args:
        sources: 数据来源列表（``github``、``rss``）。
        limit: 每个来源的最大采集条数。
        dry_run: 干跑模式开关。
        github_token: GitHub 个人访问令牌。
        rss_config: RSS 配置文件路径，为 ``None`` 时使用默认配置。
    """
    logger.info("=" * 60)
    logger.info("流水线启动: sources=%s, limit=%d, dry_run=%s", sources, limit, dry_run)

    date_str = _today_str()
    raw_path = str(RAW_DIR / f"all-{date_str}.json")

    # ---- Step 1: 采集 ----
    all_collected: list[CollectedItem] = []
    if "github" in sources:
        gh_items = collect_github(limit=limit, github_token=github_token)
        all_collected.extend(gh_items)
    if "rss" in sources:
        rss_sources = _load_rss_config(rss_config)
        rss_items = collect_rss(sources=rss_sources, limit=limit)
        all_collected.extend(rss_items)

    if not all_collected:
        logger.warning("采集结果为空，流水线终止")
        return

    logger.info("Step 1 采集完成: 共 %d 条", len(all_collected))

    # ---- Step 2: 分析 ----
    analyzed = analyze_items(all_collected, dry_run=dry_run)
    logger.info("Step 2 分析完成: 共 %d 条", len(analyzed))

    # ---- Step 3: 整理 ----
    organized = organize_items(analyzed, raw_path, ARTICLES_DIR)
    if not organized:
        logger.warning("整理后无有效条目，流水线终止")
        return
    logger.info("Step 3 整理完成: 共 %d 条", len(organized))

    # ---- Step 4: 保存 ----
    save_items(organized, all_collected, dry_run=dry_run)
    logger.info("Step 4 保存完成")
    logger.info("流水线执行完毕")


# ===================================================================
# CLI
# ===================================================================


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数列表，为 ``None`` 时使用 ``sys.argv[1:]``。

    Returns:
        解析后的命名空间。
    """
    parser = argparse.ArgumentParser(
        description="AI 知识库自动化流水线 — 采集、分析、整理、保存四步管道",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  python pipeline/pipeline.py --sources github,rss --limit 20
  python pipeline/pipeline.py --sources github --limit 5
  python pipeline/pipeline.py --sources rss --limit 10
  python pipeline/pipeline.py --sources github --limit 5 --dry-run
  python pipeline/pipeline.py --sources github,rss --verbose
""",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="github,rss",
        help="数据来源，逗号分隔，可选: github, rss (默认: github,rss)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="每个来源的最大采集条数 (默认: 20)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干跑模式: 采集和分析但不保存文件",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="启用 DEBUG 级别详细日志",
    )
    parser.add_argument(
        "--github-token",
        type=str,
        default=None,
        help="GitHub 个人访问令牌 (提高 API 速率限制)",
    )
    parser.add_argument(
        "--rss-config",
        type=Path,
        default=None,
        help="RSS 源配置文件路径 (YAML，默认: pipeline/rss_sources.yaml)",
    )
    return parser.parse_args(argv)


def _setup_logging(verbose: bool = False) -> None:
    """配置日志输出格式和级别。

    Args:
        verbose: 是否启用 DEBUG 级别。
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。

    Args:
        argv: 命令行参数列表。

    Returns:
        退出码（0 成功，1 失败）。
    """
    args = _parse_args(argv)
    _setup_logging(verbose=args.verbose)

    source_list = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
    invalid = [s for s in source_list if s not in VALID_SOURCES]
    if invalid:
        logger.error("无效的数据来源: %s，可选: %s", invalid, sorted(VALID_SOURCES))
        return 1

    try:
        run_pipeline(
            sources=source_list,
            limit=args.limit,
            dry_run=args.dry_run,
            github_token=args.github_token,
            rss_config=args.rss_config,
        )
    except Exception:
        logger.exception("流水线执行异常")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
