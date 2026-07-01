#!/usr/bin/env python3
"""知识条目 JSON 文件校验工具。

用法:
    python hooks/validate_json.py <json_file> [json_file2 ...]
    python hooks/validate_json.py knowledge/articles/*.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

VALID_STATUSES: frozenset[str] = frozenset(
    {"draft", "review", "published", "archived"}
)

VALID_AUDIENCES: frozenset[str] = frozenset(
    {"beginner", "intermediate", "advanced"}
)

ID_PATTERN: re.Pattern[str] = re.compile(r"^[a-z_]+-\d{8}-\d{3}$")

URL_PATTERN: re.Pattern[str] = re.compile(r"^https?://\S+$")

SUMMARY_MIN_LENGTH: int = 20


class ValidationError:
    """单条校验错误记录。"""

    def __init__(self, file_path: str, field: str, message: str) -> None:
        self.file_path = file_path
        self.field = field
        self.message = message

    def __str__(self) -> str:
        return f"  [{self.field}] {self.message}"


def collect_files(paths: list[str]) -> list[Path]:
    """根据输入路径收集所有 JSON 文件。

    支持显式文件路径和通配符（如 ``*.json``）。
    不存在或未匹配到任何文件的路径会打印警告到 stderr 并跳过。

    Args:
        paths: 文件路径或通配符列表。

    Returns:
        排序后的 ``Path`` 对象列表（仅现有 ``.json`` 文件）。
    """
    files: list[Path] = []
    for raw_path in paths:
        if "*" in raw_path or "?" in raw_path:
            expanded = sorted(Path().glob(raw_path))
            if not expanded:
                print(
                    f"警告: 通配符 '{raw_path}' 未匹配到任何文件，已跳过。",
                    file=sys.stderr,
                )
            for fp in expanded:
                if fp.suffix == ".json" and fp.is_file():
                    files.append(fp)
        else:
            p = Path(raw_path)
            if p.is_file():
                files.append(p)
            else:
                print(
                    f"警告: '{raw_path}' 不是有效文件，已跳过。",
                    file=sys.stderr,
                )
    return files


def validate_id(value: str) -> str | None:
    """校验 ``id`` 字段格式是否为 ``{source}-{YYYYMMDD}-{NNN}``。

    Args:
        value: JSON 条目中的 ``id`` 字段值。

    Returns:
        校验失败时返回错误描述字符串，通过则返回 ``None``。
    """
    if not isinstance(value, str):
        return f"期望 str 类型，实际为 {type(value).__name__}"
    if not ID_PATTERN.match(value):
        return (
            f"ID 格式错误 '{value}'，"
            "期望格式: {source}-{YYYYMMDD}-{NNN} "
            "（例如 github_trending-20260317-001）"
        )
    return None


def validate_status(value: str) -> str | None:
    """校验 ``status`` 是否为合法取值。

    Args:
        value: JSON 条目中的 ``status`` 字段值。

    Returns:
        校验失败时返回错误描述字符串，通过则返回 ``None``。
    """
    if not isinstance(value, str):
        return f"期望 str 类型，实际为 {type(value).__name__}"
    if value not in VALID_STATUSES:
        allowed = "、".join(sorted(VALID_STATUSES))
        return f"无效状态 '{value}'，允许值: {allowed}"
    return None


def validate_source_url(value: str) -> str | None:
    """校验 ``source_url`` 是否为合法 HTTP(S) URL。

    Args:
        value: JSON 条目中的 ``source_url`` 字段值。

    Returns:
        校验失败时返回错误描述字符串，通过则返回 ``None``。
    """
    if not isinstance(value, str):
        return f"期望 str 类型，实际为 {type(value).__name__}"
    if not URL_PATTERN.match(value):
        return f"URL 格式无效: '{value}'"
    return None


def validate_summary(value: str) -> str | None:
    """校验 ``summary`` 是否满足最小长度要求。

    Args:
        value: JSON 条目中的 ``summary`` 字段值。

    Returns:
        校验失败时返回错误描述字符串，通过则返回 ``None``。
    """
    if not isinstance(value, str):
        return f"期望 str 类型，实际为 {type(value).__name__}"
    if len(value) < SUMMARY_MIN_LENGTH:
        return (
            f"摘要过短（{len(value)} 字），"
            f"最少要求 {SUMMARY_MIN_LENGTH} 字"
        )
    return None


def validate_tags(value: list) -> str | None:
    """校验 ``tags`` 是否为非空字符串列表。

    Args:
        value: JSON 条目中的 ``tags`` 字段值。

    Returns:
        校验失败时返回错误描述字符串，通过则返回 ``None``。
    """
    if not isinstance(value, list):
        return f"期望 list 类型，实际为 {type(value).__name__}"
    if len(value) < 1:
        return "标签列表不能为空，至少需要 1 个标签"
    for i, tag in enumerate(value):
        if not isinstance(tag, str):
            return f"tags[{i}] 期望 str 类型，实际为 {type(tag).__name__}"
    return None


def validate_score(value: object) -> str | None:
    """校验 ``score`` 是否为 [1, 10] 范围内的整数。

    显式拒绝布尔值（``bool`` 是 ``int`` 的子类）。

    Args:
        value: ``score`` 字段值（可以是 int 或 float）。

    Returns:
        校验失败时返回错误描述字符串，通过则返回 ``None``。
    """
    if isinstance(value, bool):
        return "期望 int 类型，实际为 bool"
    if not isinstance(value, (int, float)):
        return f"期望 int 类型，实际为 {type(value).__name__}"
    if isinstance(value, float) and not value.is_integer():
        return f"score 必须为整数，当前为 float {value}"
    if value < 1 or value > 10:
        return f"score 取值 {value} 超出范围 [1, 10]"
    return None


def validate_audience(value: str) -> str | None:
    """校验 ``audience`` 是否为允许的受众级别之一。

    Args:
        value: JSON 条目中的 ``audience`` 字段值。

    Returns:
        校验失败时返回错误描述字符串，通过则返回 ``None``。
    """
    if not isinstance(value, str):
        return f"期望 str 类型，实际为 {type(value).__name__}"
    if value not in VALID_AUDIENCES:
        allowed = "、".join(sorted(VALID_AUDIENCES))
        return f"无效受众 '{value}'，允许值: {allowed}"
    return None


def validate_file(file_path: Path) -> list[ValidationError]:
    """校验单个 JSON 知识条目文件。

    Args:
        file_path: 待校验的 JSON 文件路径。

    Returns:
        ``ValidationError`` 列表（空列表表示文件通过全部校验）。
    """
    errors: list[ValidationError] = []
    path_str = str(file_path)

    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        errors.append(
            ValidationError(path_str, "JSON", f"解析失败: {e}")
        )
        return errors
    except OSError as e:
        errors.append(
            ValidationError(path_str, "FILE", f"读取失败: {e}")
        )
        return errors

    if not isinstance(data, dict):
        errors.append(
            ValidationError(
                path_str,
                "ROOT",
                f"期望 JSON 对象，实际为 {type(data).__name__}",
            )
        )
        return errors

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in data:
            errors.append(
                ValidationError(path_str, field, "缺少必填字段")
            )
            continue
        if not isinstance(data[field], expected_type):
            errors.append(
                ValidationError(
                    path_str,
                    field,
                    f"类型错误: 期望 {expected_type.__name__}，"
                    f"实际为 {type(data[field]).__name__}",
                )
            )

    id_value = data.get("id")
    if isinstance(id_value, str) and "id" in data:
        err = validate_id(id_value)
        if err:
            errors.append(ValidationError(path_str, "id", err))

    status_value = data.get("status")
    if isinstance(status_value, str) and "status" in data:
        err = validate_status(status_value)
        if err:
            errors.append(ValidationError(path_str, "status", err))

    url_value = data.get("source_url")
    if isinstance(url_value, str) and "source_url" in data:
        err = validate_source_url(url_value)
        if err:
            errors.append(ValidationError(path_str, "source_url", err))

    summary_value = data.get("summary")
    if isinstance(summary_value, str) and "summary" in data:
        err = validate_summary(summary_value)
        if err:
            errors.append(ValidationError(path_str, "summary", err))

    tags_value = data.get("tags")
    if isinstance(tags_value, list) and "tags" in data:
        err = validate_tags(tags_value)
        if err:
            errors.append(ValidationError(path_str, "tags", err))

    score_value = data.get("score")
    if score_value is not None:
        err = validate_score(score_value)
        if err:
            errors.append(ValidationError(path_str, "score", err))

    audience_value = data.get("audience")
    if audience_value is not None:
        err = validate_audience(audience_value)
        if err:
            errors.append(ValidationError(path_str, "audience", err))

    return errors


def main() -> int:
    """脚本入口。

    解析命令行参数、收集文件、逐个校验并输出汇总统计。
    全部文件通过时 exit 0，否则 exit 1。

    Returns:
        退出码（0 全部通过，1 存在未通过文件）。
    """
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="知识条目 JSON 文件校验工具",
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="待校验的 JSON 文件（支持 *.json 和 ? 通配符）",
    )
    args = parser.parse_args()

    files = collect_files(args.files)
    if not files:
        print(
            "错误: 未找到匹配的 JSON 文件。",
            file=sys.stderr,
        )
        return 1

    total_errors = 0
    passed = 0
    failed = 0

    for file_path in files:
        errors = validate_file(file_path)
        if errors:
            failed += 1
            total_errors += len(errors)
            print(f"[✗] 未通过: {file_path}")
            for error in errors:
                print(error)
            print()
        else:
            passed += 1
            print(f"[✓] 通过: {file_path}")

    print(
        f"\n共检查 {len(files)} 个文件，通过 {passed}，未通过 {failed}，"
        f"共 {total_errors} 个错误"
    )

    return 0 if passed == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
