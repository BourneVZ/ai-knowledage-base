"""core.utils — 采集/整理阶段共用的纯函数工具。

集中承载 V2 流水线（``pipeline``）与 V3 工作流（``workflows``）中重复出现的
文本清洗、条目 ID 生成、RSS 解析、历史 URL 去重等纯函数，避免各子系统各自
维护一份实现，减少行为分叉。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    """将文本转换为文件名安全的 ASCII slug（仅小写字母/数字/连字符）。

    中文等非 ASCII 字符会被剔除，结果可能为空字符串，调用方需自行兜底。

    Args:
        text: 原始文本（如仓库名、标题）。

    Returns:
        仅含小写字母、数字和连字符的 slug。
    """
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


def make_article_id(source: object, date_compact: str, index: int) -> str:
    """生成符合项目规范的条目 ID（``{source}-{YYYYMMDD}-{NNN}``）。

    来源段仅保留小写字母与下划线（匹配 ``hooks/validate_json.py`` 的
    ``ID_PATTERN`` ``^[a-z_]+-\\d{8}-\\d{3}$``），``rss/xxx`` 会归一为 ``xxx``，
    非法来源回退为 ``unknown``。

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


def load_existing_urls(articles_dir: str | Path) -> set[str]:
    """扫描已有文章目录，提取所有 ``source_url`` 用于历史去重。

    Args:
        articles_dir: 知识条目目录路径（``str`` 或 ``Path``）。

    Returns:
        已存在的 ``source_url`` 集合。
    """
    existing: set[str] = set()
    path = Path(articles_dir)
    if not path.is_dir():
        return existing
    for fpath in path.glob("*.json"):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("跳过无法解析的已有文章: %s", fpath)
            continue
        if not isinstance(data, dict):
            logger.debug("跳过非文章对象文件: %s", fpath)
            continue
        url = data.get("source_url", "")
        if isinstance(url, str) and url:
            existing.add(url)
    return existing


def parse_rss_items(xml_text: str) -> list[dict[str, str]]:
    """用正则从 RSS XML 中提取所有 ``<item>`` 块的字段。

    采用正则而非 XML 库解析，针对 RSS 2.0 常见结构做容错处理。

    Args:
        xml_text: RSS/Atom XML 原始文本。

    Returns:
        条目列表，每项含 ``title``、``link``、``description``、``pub_date``。
    """
    items: list[dict[str, str]] = []
    item_blocks = re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL)
    for block in item_blocks:
        title_match = re.search(r"<title>(.*?)</title>", block, re.DOTALL)
        link_match = re.search(r"<link>(.*?)</link>", block, re.DOTALL)
        desc_match = re.search(r"<description>(.*?)</description>", block, re.DOTALL)
        pub_match = re.search(r"<pubDate>(.*?)</pubDate>", block, re.DOTALL)
        items.append(
            {
                "title": decode_xml(title_match.group(1).strip())
                if title_match
                else "",
                "link": link_match.group(1).strip() if link_match else "",
                "description": decode_xml(desc_match.group(1).strip())
                if desc_match
                else "",
                "pub_date": pub_match.group(1).strip() if pub_match else "",
            }
        )
    return items


def decode_xml(text: str) -> str:
    """简易 XML 实体解码（CDATA + 常见 HTML/XML 实体）。

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


def strip_html(text: str) -> str:
    """去除 HTML 标签，返回纯文本。

    Args:
        text: 可能含 HTML 的文本。

    Returns:
        去除标签后的纯文本。
    """
    return re.sub(r"<[^>]*>", "", text).strip()
