"""Router 模式 — 基于意图分类的请求路由

两层分类策略:
1. 关键词快速匹配 — 零成本，覆盖常见场景
2. LLM 分类 — 处理模糊意图，确保不漏判
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

# 支持 `python patterns/router.py` 直接运行：脚本模式下 sys.path[0] 是脚本
# 所在目录（patterns/），需额外加入项目根目录才能解析 `core.*`。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.llm import Usage, chat_with_retry  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# chat / chat_json 适配器（模拟 workflow 中的接口签名）
# ---------------------------------------------------------------------------


def chat(
    prompt: str,
    *,
    system: str = "",
    max_tokens: int = 4096,
) -> tuple[str, Usage]:
    """发送聊天请求，返回 ``(文本, Usage)`` 元组。

    Args:
        prompt: 用户提示词。
        system: 系统提示词。
        max_tokens: 最大生成 token 数。

    Returns:
        ``(response_text, Usage)`` 元组。
    """
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    response = chat_with_retry(messages, max_tokens=max_tokens)
    return response.content, response.usage


def chat_json(
    prompt: str,
    *,
    system: str = "",
    max_tokens: int = 4096,
) -> tuple[dict[str, Any], Usage]:
    """发送聊天请求并解析为 JSON，返回 ``(dict, Usage)`` 元组。

    Args:
        prompt: 用户提示词。
        system: 系统提示词。
        max_tokens: 最大生成 token 数。

    Returns:
        ``(parsed_json_dict, Usage)`` 元组，解析失败时返回空 dict。
    """
    text, usage = chat(prompt, system=system, max_tokens=max_tokens)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("chat_json 解析失败，返回空 dict。原文: %s", text[:200])
        data = {}
    return data, usage


# ---------------------------------------------------------------------------
# 处理器定义
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 30


def github_search_handler(query: str) -> str:
    """GitHub 搜索处理器：搜索相关仓库并返回摘要。

    Args:
        query: 用户原始查询。

    Returns:
        格式化的搜索结果字符串。
    """
    search_query = query.replace("搜索", "").replace("github", "").strip()
    encoded_query = urllib.parse.quote(search_query)
    url = (
        f"https://api.github.com/search/repositories"
        f"?q={encoded_query}&sort=stars&per_page=5"
    )
    headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}

    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            data: dict[str, object] = json.loads(resp.read().decode())

        results: list[str] = []
        items: object = data.get("items")
        if isinstance(items, list):
            for repo in items:
                if not isinstance(repo, dict):
                    continue
                full_name = repo.get("full_name", "")
                html_url = repo.get("html_url", "")
                stars = repo.get("stargazers_count", 0)
                desc = repo.get("description", "")
                results.append(
                    f"- [{full_name}]({html_url}) \u2b50{stars} \u2014 {desc}"
                )
        return (
            "GitHub \u641c\u7d22\u7ed3\u679c:\n" + "\n".join(results)
            if results
            else "\u672a\u627e\u5230\u76f8\u5173\u4ed3\u5e93"
        )
    except Exception as e:
        logger.error("GitHub \u641c\u7d22\u5931\u8d25: %s", e)
        return f"GitHub \u641c\u7d22\u5931\u8d25: {e}"


def _build_article_index() -> list[dict[str, Any]]:
    """从 ``knowledge/articles/`` 目录构建全文索引。

    Returns:
        所有文章 JSON 对象组成的列表。
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    articles_dir = os.path.join(base_dir, "knowledge", "articles")

    if not os.path.exists(articles_dir):
        logger.warning("knowledge/articles/ \u4e0d\u5b58\u5728")
        return []

    index: list[dict[str, Any]] = []
    for filename in os.listdir(articles_dir):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(articles_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                entry: dict[str, Any] = json.load(f)
            entry["_filename"] = filename
            index.append(entry)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("\u8df3\u8fc7\u65e0\u6548\u6587\u4ef6 %s: %s", filename, e)

    return index


def knowledge_query_handler(query: str) -> str:
    """知识库查询处理器：从本地 JSON 文件检索。

    Args:
        query: 用户查询关键词。

    Returns:
        格式化的检索结果字符串。
    """
    index = _build_article_index()

    if not index:
        return "\u77e5\u8bc6\u5e93\u4e3a\u7a7a\uff0c\u8bf7\u5148\u8fd0\u884c\u91c7\u96c6\u5de5\u4f5c\u6d41\u3002"

    query_lower = query.lower()
    matches: list[dict[str, Any]] = []

    for entry in index:
        title = (entry.get("title", "") or "").lower()
        summary = (entry.get("summary", "") or "").lower()
        category = (entry.get("category", "") or "").lower()
        tags: list[str] = entry.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        tags_lower = [t.lower() for t in tags]

        if (
            query_lower in title
            or query_lower in summary
            or query_lower in category
            or any(query_lower in t for t in tags_lower)
        ):
            matches.append(entry)

    if matches:
        lines = [
            f"- {m.get('title', '??')} | {m.get('category', '??')} | "
            f"\u2b50{m.get('stars', '?'):}"
            for m in matches[:10]
        ]
        return (
            f"\u627e\u5230 {len(matches)} \u6761\u76f8\u5173\u77e5\u8bc6:\n"
            + "\n".join(lines)
        )
    return "\u672a\u627e\u5230\u5339\u914d\u7684\u77e5\u8bc6\u6761\u76ee\u3002"


def general_chat_handler(query: str) -> str:
    """通用对话处理器：LLM 直接回答。

    Args:
        query: 用户查询。

    Returns:
        LLM 响应的文本内容。
    """
    result, _ = chat(
        query,
        system="\u4f60\u662f\u4e00\u4e2a\u4e13\u4e1a\u7684 AI \u6280\u672f\u987e\u95ee\u3002\u7b80\u6d01\u3001\u51c6\u786e\u5730\u56de\u7b54\u3002",
    )
    return result


# ---------------------------------------------------------------------------
# 路由器核心
# ---------------------------------------------------------------------------

HANDLERS: dict[str, Callable[[str], str]] = {
    "github_search": github_search_handler,
    "knowledge_query": knowledge_query_handler,
    "general_chat": general_chat_handler,
}

KEYWORD_RULES: list[tuple[list[str], str]] = [
    (
        ["github", "\u4ed3\u5e93", "repo", "\u641c\u7d22\u9879\u76ee", "trending"],
        "github_search",
    ),
    (
        [
            "\u77e5\u8bc6\u5e93",
            "\u67e5\u8be2",
            "\u68c0\u7d22",
            "\u5df2\u6536\u5f55",
            "knowledge",
        ],
        "knowledge_query",
    ),
]


def classify_intent(query: str) -> str:
    """意图分类：关键词匹配优先，LLM 兜底。

    Args:
        query: 用户查询。

    Returns:
        分类后的意图名称，始终是 ``HANDLERS`` 的有效 key。
    """
    query_lower = query.lower()

    for keywords, intent in KEYWORD_RULES:
        if any(kw in query_lower for kw in keywords):
            return intent

    prompt = f"""请判断以下用户查询的意图类别。

查询: {query}

可选类别:
- github_search: 想搜索 GitHub 上的项目
- knowledge_query: 想查询已有的知识库内容
- general_chat: 一般性技术问题

请只返回类别名称。"""

    result, _ = chat(
        prompt,
        system="你是意图分类器。只返回类别名称。",
        max_tokens=50,
    )
    intent = result.strip().lower()
    return intent if intent in HANDLERS else "general_chat"


def route(query: str) -> str:
    """路由器入口：分类意图并调用对应处理器。

    Args:
        query: 用户查询。

    Returns:
        处理器返回的结果字符串。
    """
    intent = classify_intent(query)
    print(f"[Router] 意图: {intent}")
    return HANDLERS[intent](query)


# ---------------------------------------------------------------------------
# 测试入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s | %(name)s | %(message)s",
    )

    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "搜索最近的 AI Agent 框架"
    print(f"查询: {query}\n")
    print(route(query))
