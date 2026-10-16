"""RSS 源配置加载 — V2 流水线与 V3 工作流共用的单一配置源。

从项目根目录 ``rss_sources.yaml`` 读取启用的 RSS 源；文件缺失或 PyYAML 未安装时
回退到内置默认源。返回 ``{源名称: URL}`` 映射。
"""

from __future__ import annotations

import logging
from pathlib import Path

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_RSS_SOURCES: dict[str, str] = {
    "hn": "https://hnrss.org/newest?q=ai+OR+llm+OR+agent+OR+machine+learning",
    "arxiv": "https://rss.arxiv.org/rss/cs.AI",
}
"""内置默认 RSS 源，作为 YAML 配置缺失/解析失败时的回退。"""

DEFAULT_RSS_CONFIG: Path = Path(__file__).resolve().parent.parent / "rss_sources.yaml"
"""RSS 配置文件默认路径（项目根目录）。"""


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------


def load_rss_sources(yaml_path: Path | None = None) -> dict[str, str]:
    """加载启用的 RSS 源（优先 YAML，回退内置默认）。

    Args:
        yaml_path: YAML 配置文件路径，为 ``None`` 时使用默认路径。

    Returns:
        RSS 源名称到 URL 的映射。
    """
    if yaml is None:
        logger.info("PyYAML 未安装，使用内置默认 RSS 源")
        return dict(DEFAULT_RSS_SOURCES)

    path = yaml_path or DEFAULT_RSS_CONFIG
    if not path.is_file():
        logger.warning("RSS 配置文件 %s 不存在，使用内置默认 RSS 源", path)
        return dict(DEFAULT_RSS_SOURCES)

    try:
        with path.open("r", encoding="utf-8") as f:
            data: dict[str, object] = yaml.safe_load(f)
    except Exception as e:
        logger.warning("RSS 配置文件解析失败: %s，使用内置默认 RSS 源", e)
        return dict(DEFAULT_RSS_SOURCES)

    if not isinstance(data, dict):
        logger.warning("RSS 配置文件格式错误，使用内置默认 RSS 源")
        return dict(DEFAULT_RSS_SOURCES)

    raw_sources: object = data.get("sources")
    if not isinstance(raw_sources, list):
        logger.warning("RSS 配置缺少 sources 列表，使用内置默认 RSS 源")
        return dict(DEFAULT_RSS_SOURCES)

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
        return dict(DEFAULT_RSS_SOURCES)

    logger.info("从 %s 加载了 %d 个 RSS 源", path, len(enabled))
    for name, url in enabled.items():
        logger.debug("  %s → %s", name, url)
    return enabled
