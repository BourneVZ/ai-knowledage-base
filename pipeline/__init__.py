"""pipeline 包 — AI 知识库数据处理管线（V2 四步管道）。

采集、分析、整理、保存四步管道执行脚本（pipeline.py）所在包。
模型调用客户端与配置/RSS 源加载已抽离至 ``core`` 包，本包不再承载共享基础设施。
"""

from __future__ import annotations
