#!/usr/bin/env python3
"""MCP Server for local knowledge base search over knowledge/articles/ JSON files.

Implements JSON-RPC 2.0 over stdio with MCP protocol methods:
initialize, tools/list, tools/call, ping.

Usage:
    python mcp_knowledge_server.py

Environment variables:
    KNOWLEDGE_ARTICLES_DIR  Override articles directory (default: knowledge/articles/)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


ARTICLES_DIR = Path(
    os.environ.get(
        "KNOWLEDGE_ARTICLES_DIR",
        Path(__file__).resolve().parent / "knowledge" / "articles",
    )
)

SERVER_NAME = "knowledge-base-mcp"
SERVER_VERSION = "1.0.0"


class KnowledgeBase:
    def __init__(self, articles_dir: Path) -> None:
        self.articles: list[dict[str, Any]] = []
        self._load_articles(articles_dir)

    def _load_articles(self, articles_dir: Path) -> None:
        if not articles_dir.exists():
            return

        for file_path in sorted(articles_dir.glob("*.json")):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            if "items" in data and isinstance(data["items"], list):
                for item in data["items"]:
                    article = self._normalize_analysis_item(
                        item, data, file_path.stem
                    )
                    self.articles.append(article)
            else:
                self.articles.append(data)

    @staticmethod
    def _normalize_analysis_item(
        item: dict[str, Any], parent: dict[str, Any], file_key: str
    ) -> dict[str, Any]:
        name = item.get("name", "unknown")
        article_id = f"{file_key}-{name.replace('/', '-').replace(' ', '-')}"
        return {
            "id": article_id,
            "title": name,
            "source": parent.get("source", "tech-summary"),
            "source_url": item.get("url", ""),
            "description": "",
            "summary": item.get("summary", ""),
            "tags": [],
            "category": "",
            "status": "draft",
            "stars": None,
            "authors": [],
            "collected_at": parent.get("analyzed_at", ""),
            "analyzed_at": parent.get("analyzed_at", ""),
            "published_at": None,
            "innovation_score": item.get("score"),
            "difficulty_score": None,
            "key_points": item.get("highlights", []),
            "risks": item.get("risks", []),
            "raw_path": f"knowledge/articles/{file_key}.json",
            "metadata": {},
        }

    def search(self, keyword: str, limit: int = 5) -> list[dict[str, Any]]:
        kw = keyword.lower()
        results: list[dict[str, Any]] = []
        for article in self.articles:
            title = (article.get("title") or "").lower()
            summary = (article.get("summary") or "").lower()
            description = (article.get("description") or "").lower()
            tags_text = " ".join(
                t.lower().strip() for t in (article.get("tags") or [])
            )
            searchable = f"{title} {summary} {description} {tags_text}"
            if kw in searchable:
                results.append(
                    {
                        "id": article.get("id"),
                        "title": article.get("title"),
                        "source": article.get("source"),
                        "source_url": article.get("source_url"),
                        "summary": article.get("summary"),
                        "tags": article.get("tags"),
                        "category": article.get("category"),
                    }
                )
                if len(results) >= limit:
                    break
        return results

    def get_article(self, article_id: str) -> dict[str, Any] | None:
        for article in self.articles:
            if article.get("id") == article_id:
                return article
        return None

    def stats(self) -> dict[str, Any]:
        total = len(self.articles)
        sources: dict[str, int] = {}
        all_tags: dict[str, int] = {}
        categories: dict[str, int] = {}
        statuses: dict[str, int] = {}

        for article in self.articles:
            src = article.get("source", "unknown")
            sources[src] = sources.get(src, 0) + 1

            for tag in article.get("tags") or []:
                tag = tag.strip().lower()
                if tag and tag != "placeholder":
                    all_tags[tag] = all_tags.get(tag, 0) + 1

            cat = article.get("category", "")
            if cat:
                categories[cat] = categories.get(cat, 0) + 1

            st = article.get("status", "unknown")
            statuses[st] = statuses.get(st, 0) + 1

        popular_tags = sorted(
            all_tags.items(), key=lambda x: x[1], reverse=True
        )[:10]

        return {
            "total_articles": total,
            "source_distribution": sources,
            "category_distribution": categories,
            "status_distribution": statuses,
            "popular_tags": dict(popular_tags),
        }


def _dispatch(method: str, params: dict[str, Any], kb: KnowledgeBase) -> dict[str, Any]:
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    elif method == "ping":
        return {}
    elif method == "tools/list":
        return {
            "tools": [
                {
                    "name": "search_articles",
                    "description": (
                        "Search knowledge base articles by keyword in title, "
                        "summary, description, and tags."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "Search keyword",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Max results to return (default 5)",
                            },
                        },
                        "required": ["keyword"],
                    },
                },
                {
                    "name": "get_article",
                    "description": "Get full article content by article ID.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "article_id": {
                                "type": "string",
                                "description": "Unique article ID",
                            },
                        },
                        "required": ["article_id"],
                    },
                },
                {
                    "name": "knowledge_stats",
                    "description": (
                        "Return knowledge base statistics: total articles, "
                        "source distribution, popular tags, category and "
                        "status breakdowns."
                    ),
                    "inputSchema": {"type": "object", "properties": {}},
                },
            ]
        }
    elif method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        result_text: str
        if name == "search_articles":
            keyword = str(arguments.get("keyword", ""))
            limit = int(arguments.get("limit", 5))
            results = kb.search(keyword, limit)
            result_text = json.dumps(results, ensure_ascii=False, indent=2)
        elif name == "get_article":
            article_id = str(arguments.get("article_id", ""))
            article = kb.get_article(article_id)
            if article is None:
                result_text = f"Article not found: {article_id}"
            else:
                result_text = json.dumps(article, ensure_ascii=False, indent=2)
        elif name == "knowledge_stats":
            stats = kb.stats()
            result_text = json.dumps(stats, ensure_ascii=False, indent=2)
        else:
            raise ValueError(f"Unknown tool: {name}")
        return {"content": [{"type": "text", "text": result_text}]}
    else:
        raise ValueError(f"Unknown method: {method}")


def _send_response(req_id: Any, result: dict[str, Any]) -> None:
    response: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result,
    }
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _send_error(req_id: Any, code: int, message: str) -> None:
    response: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle_mcp(kb: KnowledgeBase) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        if "id" not in request:
            continue

        req_id = request["id"]
        method = request.get("method", "")
        params = request.get("params", {})

        try:
            result = _dispatch(method, params, kb)
            _send_response(req_id, result)
        except Exception as exc:
            _send_error(req_id, -32603, str(exc))


def main() -> None:
    articles_dir = ARTICLES_DIR
    if not articles_dir.exists():
        sys.stderr.write(f"Articles directory not found: {articles_dir}\n")
        sys.stderr.flush()
        articles_dir.mkdir(parents=True, exist_ok=True)

    kb = KnowledgeBase(articles_dir)
    sys.stderr.write(
        f"[{SERVER_NAME}] Loaded {len(kb.articles)} articles from {articles_dir}\n"
    )
    sys.stderr.flush()
    handle_mcp(kb)


if __name__ == "__main__":
    main()
