#!/usr/bin/env python3
"""统一 LLM 调用客户端。

通过环境变量切换模型提供商，基于 ``httpx`` 直连 OpenAI 兼容 API，
提供重试、Token 估算和成本计算能力。

支持的提供商:
- DeepSeek
- Qwen (通义千问)
- OpenAI

用法::

    from pipeline.model_client import quick_chat, chat_with_retry

    answer = quick_chat("什么是 RAG？")
    print(answer)

    response = chat_with_retry([
        {"role": "system", "content": "你是一个技术助理。"},
        {"role": "user", "content": "解释 Transformer 架构。"},
    ])
    print(f"内容: {response.content}")
    print(f"用量: {response.usage.total_tokens} tokens")
"""

from __future__ import annotations

import copy
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

# ---------------------------------------------------------------------------
# .env 自动加载
# ---------------------------------------------------------------------------


def _load_dotenv() -> None:
    """尝试从项目根目录加载 ``.env`` 文件。

    不依赖 python-dotenv 也能运行，缺失时静默跳过。
    """
    try:
        from dotenv import load_dotenv as _ld

        _ld(override=False)
    except ImportError:
        pass


_load_dotenv()

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

ENV_PROVIDER: str = "LLM_PROVIDER"
"""切换提供商的环墧变量名。"""

ENV_API_KEY: str = "LLM_API_KEY"
"""通用 API Key 环墧变量名（作为提供商专属 key 的 fallback）。"""

DEFAULT_PROVIDER: str = "deepseek"
"""未设置 ``LLM_PROVIDER`` 时的默认提供商。"""


def _env_float(key: str, default: float) -> float:
    """读取浮点型环境变量，解析失败时返回默认值。"""
    raw = os.getenv(key, "")
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    """读取整型环境变量，解析失败时返回默认值。"""
    raw = os.getenv(key, "")
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


DEFAULT_TIMEOUT: float = _env_float("LLM_TIMEOUT", 60.0)
"""全局请求超时（秒），可通过 ``LLM_TIMEOUT`` 覆盖。"""

MAX_RETRIES: int = _env_int("LLM_MAX_RETRIES", 3)
"""重试最大次数（总共 MAX_RETRIES + 1 次尝试），可通过 ``LLM_MAX_RETRIES`` 覆盖。"""

BASE_DELAY: float = 1.0
MAX_DELAY: float = 60.0
DEFAULT_TEMPERATURE: float = 0.7
DEFAULT_MAX_TOKENS: int = 4096

_CHARS_PER_TOKEN_ENGLISH: float = 4.0
_CHARS_PER_TOKEN_CHINESE: float = 1.5

_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "env_key": "QWEN_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "env_key": "OPENAI_API_KEY",
    },
}
"""提供商硬编码默认值，可被同名大写环境变量覆盖。"""


def _get_provider_configs() -> dict[str, dict[str, str]]:
    """合并环境变量覆盖后的提供商配置。

    每个提供商支持以下环境变量覆盖:
    - ``{NAME}_BASE_URL`` → ``base_url``
    - ``{NAME}_DEFAULT_MODEL`` → ``default_model``

    Returns:
        合并后的配置字典（深拷贝静态默认值 + 环境变量覆盖）。
    """
    configs: dict[str, dict[str, str]] = copy.deepcopy(_PROVIDER_DEFAULTS)
    for name, cfg in configs.items():
        prefix = name.upper()
        for key in ("base_url", "default_model"):
            env_val = os.getenv(f"{prefix}_{key.upper()}")
            if env_val:
                cfg[key] = env_val
    return configs


def _get_pricing() -> dict[str, dict[str, float]]:
    """合并环境变量覆盖后的定价表。

    每个提供商支持 ``{NAME}_INPUT_PRICE`` 和 ``{NAME}_OUTPUT_PRICE`` 覆盖
    默认的每 1K token 美元价格。

    Returns:
        合并后的定价字典。
    """
    defaults: dict[str, dict[str, float]] = {
        "deepseek": {"input": 0.00014, "output": 0.00028},
        "qwen": {"input": 0.00050, "output": 0.00200},
        "openai": {"input": 0.00250, "output": 0.01000},
    }
    for name in defaults:
        for kind in ("input", "output"):
            env_val = os.getenv(f"{name.upper()}_{kind.upper()}_PRICE")
            if env_val:
                try:
                    defaults[name][kind] = float(env_val)
                except ValueError:
                    logger.warning(
                        "无效的定价环境变量 %s=%s，沿用默认值。",
                        f"{name.upper()}_{kind.upper()}_PRICE",
                        env_val,
                    )
    return defaults


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class Usage:
    """API 调用 Token 用量统计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """LLM 统一返回结构。

    Attributes:
        content: 模型生成的文本内容。
        usage: Token 用量统计。
        model: 实际使用的模型名称。
        finish_reason: 完成原因（``stop``、``length``、``content_filter`` 等），
            异常时可能为 ``None``。
    """

    content: str
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    finish_reason: str | None = None


# ---------------------------------------------------------------------------
# Provider 抽象与实现
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """LLM 提供商抽象基类。

    所有提供商需实现 :meth:`chat`，返回统一的 :class:`LLMResponse`。
    """

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> LLMResponse:
        """发送聊天补全请求。

        Args:
            messages: 消息列表，每条消息包含 ``"role"``（如 ``"system"``、
                ``"user"``、``"assistant"``）和 ``"content"``。
            model: 模型名称，为 ``None`` 时使用提供商默认模型。
            temperature: 采样温度（0-2），值越高输出越随机。
            max_tokens: 生成的最大 token 数。

        Returns:
            包含生成内容和用量统计的 :class:`LLMResponse`。

        Raises:
            httpx.HTTPError: HTTP 请求或响应错误。
        """
        ...


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI 兼容 Chat Completions API 通用实现。

    通过 ``httpx`` 直接调用兼容端点的 ``/chat/completions`` 接口，
    不依赖 openai SDK。
    """

    def __init__(self, api_key: str, base_url: str, default_model: str) -> None:
        """初始化客户端。

        Args:
            api_key: API 密钥。
            base_url: API 基础 URL（如 ``https://api.deepseek.com/v1``）。
            default_model: 默认模型名称。
        """
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> LLMResponse:
        """发送聊天补全请求。

        Args:
            messages: 对话消息列表。
            model: 模型名称，默认为提供商默认模型。
            temperature: 采样温度。
            max_tokens: 最大生成 token 数。

        Returns:
            :class:`LLMResponse` 实例。

        Raises:
            httpx.HTTPStatusError: 非 2xx 响应。
            httpx.TimeoutException: 请求超时。
        """
        effective_model = model or self._default_model
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, object] = {
            "model": effective_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data: dict[str, object] = response.json()

        return self._parse_response(data, effective_model)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _parse_response(
        self, data: dict[str, object], model: str
    ) -> LLMResponse:
        """将 API 原始响应解析为 :class:`LLMResponse`。

        Args:
            data: API 返回的 JSON 对象。
            model: 请求使用的模型名称。

        Returns:
            标准化的 :class:`LLMResponse`。
        """
        choices: object = data.get("choices")
        if not isinstance(choices, list) or len(choices) == 0:
            raise ValueError(
                f"API 返回的 choices 无效: {choices}"
            )

        choice: dict[str, object] = choices[0]  # type: ignore[assignment]
        message: object = choice.get("message", {})
        if not isinstance(message, dict):
            raise ValueError(
                f"API 返回的 message 无效: {message}"
            )

        content: object = message.get("content", "")
        if not isinstance(content, str):
            content = ""

        finish_reason: object = choice.get("finish_reason")

        usage_data: object = data.get("usage", {})
        usage = Usage()
        if isinstance(usage_data, dict):
            usage = Usage(
                prompt_tokens=self._safe_int(usage_data.get("prompt_tokens")),
                completion_tokens=self._safe_int(
                    usage_data.get("completion_tokens")
                ),
                total_tokens=self._safe_int(usage_data.get("total_tokens")),
            )

        return LLMResponse(
            content=content,
            usage=usage,
            model=str(data.get("model", model)),
            finish_reason=str(finish_reason) if finish_reason is not None else None,
        )

    @staticmethod
    def _safe_int(value: object) -> int:
        """安全地将值转换为 ``int``，失败时返回 0。

        Args:
            value: 任意值。

        Returns:
            转换后的整数或 0。
        """
        try:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(value)
            if isinstance(value, str):
                return int(value)
        except (ValueError, TypeError):
            pass
        return 0


# ---------------------------------------------------------------------------
# Provider 工厂
# ---------------------------------------------------------------------------


def _resolve_api_key(provider_name: str) -> str:
    """解析指定提供商的 API Key。

    优先级: 提供商专属环境变量 > ``LLM_API_KEY``。

    Args:
        provider_name: 提供商名称（``"deepseek"``、``"qwen"``、``"openai"``）。

    Returns:
        API Key 字符串。

    Raises:
        RuntimeError: 未找到任何 API Key 环境变量。
    """
    configs = _get_provider_configs()
    config = configs[provider_name]
    provider_key = os.getenv(config["env_key"])
    if provider_key:
        return provider_key

    generic_key = os.getenv(ENV_API_KEY)
    if generic_key:
        logger.info(
            "未设置 %s，使用通用 %s 作为 fallback。",
            config["env_key"],
            ENV_API_KEY,
        )
        return generic_key

    raise RuntimeError(
        f"未找到 API Key：请设置 {config['env_key']} 或 {ENV_API_KEY} 环境变量。"
    )


def _get_provider_name() -> str:
    """获取当前配置的提供商名称。

    Returns:
        规范化后的提供商名称。
    """
    configs = _get_provider_configs()
    raw = os.getenv(ENV_PROVIDER, DEFAULT_PROVIDER).strip().lower()
    if raw not in configs:
        logger.warning(
            "未知的 LLM_PROVIDER '%s'，fallback 到默认值 '%s'。",
            raw,
            DEFAULT_PROVIDER,
        )
        return DEFAULT_PROVIDER
    return raw


def create_provider() -> LLMProvider:
    """根据环境变量创建对应的 LLM 提供商实例。

    Returns:
        配置好的 :class:`LLMProvider` 实例。

    Raises:
        RuntimeError: API Key 未配置。
        ValueError: 提供商名称无效。
    """
    provider_name = _get_provider_name()
    api_key = _resolve_api_key(provider_name)
    configs = _get_provider_configs()
    config = configs[provider_name]

    logger.info(
        "创建 LLM 提供商: provider=%s, model=%s",
        provider_name,
        config["default_model"],
    )
    return OpenAICompatibleProvider(
        api_key=api_key,
        base_url=config["base_url"],
        default_model=config["default_model"],
    )


# ---------------------------------------------------------------------------
# 带重试的聊天
# ---------------------------------------------------------------------------


def chat_with_retry(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_retries: int = MAX_RETRIES,
) -> LLMResponse:
    """带自动重试的聊天补全请求。

    在遇到网络错误或 5xx 响应时自动重试，使用指数退避策略。
    总共最多 ``max_retries + 1`` 次尝试（1 次原始请求 + max_retries 次重试）。

    Args:
        messages: 对话消息列表。
        model: 模型名称，默认使用提供商默认模型。
        temperature: 采样温度。
        max_tokens: 最大生成 token 数。
        max_retries: 最大重试次数（不含首次请求）。

    Returns:
        :class:`LLMResponse` 实例。

    Raises:
        httpx.HTTPError: 全部尝试失败。
        RuntimeError: API Key 未配置。
    """
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            provider = create_provider()
            return provider.chat(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except httpx.TimeoutException as e:
            last_error = e
            logger.warning(
                "请求超时 (attempt %d/%d): %s",
                attempt + 1,
                max_retries + 1,
                e,
            )
        except httpx.HTTPStatusError as e:
            last_error = e
            status = e.response.status_code
            if status < 500:
                logger.error(
                    "客户端错误 %d (attempt %d/%d)，不重试: %s",
                    status,
                    attempt + 1,
                    max_retries + 1,
                    e,
                )
                raise
            logger.warning(
                "服务端错误 %d (attempt %d/%d): %s",
                status,
                attempt + 1,
                max_retries + 1,
                e,
            )
        except httpx.HTTPError as e:
            last_error = e
            logger.warning(
                "网络错误 (attempt %d/%d): %s",
                attempt + 1,
                max_retries + 1,
                e,
            )

        if attempt < max_retries:
            delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
            logger.info("等待 %.1f 秒后重试...", delay)
            time.sleep(delay)
        else:
            logger.error("已达最大重试次数 %d，放弃。", max_retries)
            raise last_error  # type: ignore[misc]

    raise last_error  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Token 估算与成本计算
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """粗略估算文本的 Token 数量。

    采用字符级启发式算法：英文约 4 字符/token，中文约 1.5 字符/token。
    该估算**不精确**，仅用于预计算参考。精确计数请使用对应模型的 tokenizer。

    Args:
        text: 待估算的文本。

    Returns:
        估算的 token 数（至少为 1）。
    """
    if not text:
        return 0

    chinese_chars = 0
    english_chars = 0

    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf":
            chinese_chars += 1
        elif ch not in (" ", "\n", "\r", "\t"):
            english_chars += 1

    tokens = int(
        chinese_chars / _CHARS_PER_TOKEN_CHINESE
        + english_chars / _CHARS_PER_TOKEN_ENGLISH
    )
    return max(tokens, 1)


def _estimate_messages_tokens(messages: list[dict[str, str]]) -> int:
    """估算消息列表的总 Token 数。

    简单地将每条消息的 ``content`` 部分通过 :func:`estimate_tokens` 累加，
    未计入角色标记等格式开销，仅供成本预估。

    Args:
        messages: 对话消息列表。

    Returns:
        估算的 token 总数。
    """
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
    return total


def calculate_cost(
    usage: Usage,
    provider_name: str | None = None,
) -> float:
    """根据 Token 用量计算 USD 成本。

    定价数据取自 :data:`_DEFAULT_PRICING`，为公开参考价。
    实际费用以各提供商官方计费为准。

    Args:
        usage: Token 用量统计。
        provider_name: 提供商名称，为 ``None`` 时自动从环境变量读取。

    Returns:
        USD 金额（浮点数）。

    Raises:
        ValueError: 提供商名称无效。
    """
    effective_provider = provider_name or _get_provider_name()
    pricing_table = _get_pricing()
    if effective_provider not in pricing_table:
        raise ValueError(f"无 {effective_provider} 的定价信息。")

    pricing = pricing_table[effective_provider]
    input_cost = (usage.prompt_tokens / 1000.0) * pricing["input"]
    output_cost = (usage.completion_tokens / 1000.0) * pricing["output"]
    total_cost = input_cost + output_cost

    logger.debug(
        "成本估算: provider=%s, input=%d tokens, output=%d tokens, "
        "total=$%.6f",
        effective_provider,
        usage.prompt_tokens,
        usage.completion_tokens,
        total_cost,
    )
    return round(total_cost, 6)


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------


def quick_chat(prompt: str, *, model: str | None = None) -> str:
    """一句话调用 LLM，返回纯文本响应。

    内部使用 :func:`chat_with_retry`，适用于简单问答场景。
    需要更精细控制（如 system prompt、temperature、用量统计）时，请直接使用
    :func:`chat_with_retry`。

    Args:
        prompt: 用户输入的提示文本。
        model: 模型名称，默认使用提供商默认模型。

    Returns:
        LLM 生成的文本响应。

    Example::

        >>> from pipeline.model_client import quick_chat
        >>> answer = quick_chat("1+1 等于几？")
        >>> print(answer)
        2
    """
    messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
    response = chat_with_retry(messages, model=model)
    return response.content


# ---------------------------------------------------------------------------
# 测试入口
# ---------------------------------------------------------------------------


def _run_self_test() -> int:
    """模块自检：验证结构、估算函数等功能是否正常，不依赖真实 API Key。

    Returns:
        0 表示全部通过，1 表示存在失败。
    """
    errors: list[str] = []

    # --- 数据结构测试 ---
    usage = Usage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    response = LLMResponse(
        content="测试回复",
        usage=usage,
        model="test-model",
        finish_reason="stop",
    )

    if response.content != "测试回复":
        errors.append("LLMResponse.content 不匹配")
    if response.usage.total_tokens != 150:
        errors.append("Usage.total_tokens 不匹配")
    if response.finish_reason != "stop":
        errors.append("LLMResponse.finish_reason 不匹配")

    # --- Token 估算测试 ---
    eng_est = estimate_tokens("Hello, world!")
    if eng_est == 0:
        errors.append("英文 token 估算异常")
    logger.info("英文 'Hello, world!' 估算 token: %d", eng_est)

    cn_est = estimate_tokens("你好世界")
    if cn_est == 0:
        errors.append("中文 token 估算异常")
    logger.info("中文 '你好世界' 估算 token: %d", cn_est)

    empty_est = estimate_tokens("")
    if empty_est != 0:
        errors.append("空字符串估算应为 0")

    # --- 成本计算测试 ---
    test_usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    cost = calculate_cost(test_usage, provider_name="deepseek")
    expected_cost = (1000 / 1000 * 0.00014) + (500 / 1000 * 0.00028)
    if abs(cost - expected_cost) > 0.000001:
        errors.append(
            f"成本计算不匹配: 期望 {expected_cost}, 实际 {cost}"
        )
    logger.info("DeepSeek 成本计算: $%.6f", cost)

    cost_qwen = calculate_cost(test_usage, provider_name="qwen")
    if cost_qwen <= 0:
        errors.append("Qwen 成本计算结果异常")
    logger.info("Qwen 成本计算: $%.6f", cost_qwen)

    # --- Provider 类型测试（mock） ---
    try:
        provider: LLMProvider = OpenAICompatibleProvider(
            api_key="sk-test",
            base_url="https://api.example.com/v1",
            default_model="test-model",
        )
        if not isinstance(provider, LLMProvider):
            errors.append("OpenAICompatibleProvider 未实现 LLMProvider")
        logger.info("Provider 抽象结构校验通过")
    except Exception as e:
        errors.append(f"Provider 构造失败: {e}")

    # --- 环境变量提示 ---
    provider_name = _get_provider_name()
    logger.info("当前 LLM_PROVIDER: %s", provider_name)
    try:
        _resolve_api_key(provider_name)
        logger.info("API Key 已配置")
    except RuntimeError:
        logger.info("未检测到 API Key，跳过真实 API 测试（这是正常现象）")

    # --- 输出结果 ---
    if errors:
        for err in errors:
            print(f"[FAIL] {err}")
        return 1

    print("[OK] 所有自检通过！")
    print(f"  - 当前提供商: {provider_name}")
    print(f"  - 英文 Token 估算: {eng_est}")
    print(f"  - 中文 Token 估算: {cn_est}")
    print(f"  - DeepSeek 成本: ${cost:.6f}")
    print(f"  - Qwen 成本: ${cost_qwen:.6f}")
    return 0


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s | %(name)s | %(message)s",
    )
    sys.exit(_run_self_test())
