"""core 包 — 跨子系统共享的基础设施。

统一承载 LLM 调用客户端（:mod:`core.llm`）、项目配置加载（:mod:`core.config`）
与 RSS 源加载（:mod:`core.rss_sources`），供 V2 流水线（``pipeline``）、
V3 工作流（``workflows``）与多 Agent 模式（``patterns``）共用，避免各子系统
重复实现或反向依赖 ``pipeline``。
"""

from __future__ import annotations
