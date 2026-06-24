# AI 知识库 · 编码规范 v1.0

> 本文件内容将合并至 AGENTS.md 的「编码规范」节，覆盖并替代该节原有条目。
> 合并后不丢失任何现有约束，仅做补充和细化。

---

## 1. 格式化与 Lint

- 统一使用 **Black** 格式化，行宽 88（默认）。
- 使用 **ruff** 做 lint 和 import 排序（等效 isort，启用 I 规则）。
- 遵循 **PEP 8**，以 ruff 规则集 `E, F, W, I` 为基线。
- 所有代码通过 **mypy --strict** 类型检查（见第 3 节）。

## 2. 命名规范

| 类别 | 风格 | 示例 |
| --- | --- | --- |
| 变量、函数、方法、模块、文件名 | `snake_case` | `fetch_trending`, `source_parser.py` |
| 类名 | `PascalCase` | `GitHubCollector`, `ArticleAnalyzer` |
| 常量（模块级） | `UPPER_SNAKE_CASE` | `DEFAULT_TIMEOUT`, `MAX_RETRIES` |
| 枚举成员 | `UPPER_SNAKE_CASE` | `Status.DRAFT`, `Source.GITHUB` |
| 私有成员 | 前缀单下划线 `_` | `_validate_fields`, `self._cache` |

## 3. 类型标注

- **必须**为所有公共函数、方法和类属性添加完整的类型标注。
- 使用 Python 3.12 语法（`X | None` 而非 `Optional[X]`，`list[X]` 而非 `List[X]`）。
- 通过 **mypy --strict** 无错误才能合并到 main。

## 4. 文档

- 公共函数、类、Agent 节点**必须**编写 **Google 风格 docstring**。
- 模块级 docstring 推荐编写，描述模块职责和主要导出。
- 内部辅助函数（前缀 `_`）可省略，但复杂逻辑建议加注释。

## 5. 魔法字符串 & 硬编码

- **禁止裸魔法字符串**。符合以下任一条件的字符串必须提取：
  - 状态值（如 `"draft"`、`"published"`）→ 使用 `enum.StrEnum`
  - 多处引用的配置 key → 定义为模块常量或放入 `config` 模块
  - 来源名称、类别标签 → 定义为常量或 Enum
- JSON key 字样（如 `"source_url"`）属于数据契约，不受此限制。
- **禁止**在业务代码中硬编码 token、API key、cookie、webhook 地址等敏感信息。
  敏感值只能通过环境变量或 `.env`（不入库）注入。

## 6. TODO/FIXME 管理

- `TODO` / `FIXME` / `HACK` 标注**必须**附带 GitHub Issue 编号：`# TODO(#123): 描述`。
- **不允许**未关联 Issue 的 TODO 提交到 main。
- pre-commit hook 中配置 `rg "TODO(?!\(#\d+\))"` 阻断无编号 TODO。
- CI 中同样执行此检查作为兜底。

## 7. 网络请求

- 所有外部 HTTP 请求**必须**设置超时（connect + read），默认 30s。
- **必须**实现重试逻辑（推荐 `tenacity` 库，指数退避，最多 3 次）。
- 网络错误**必须**记录来源 URL、状态码、重试次数和异常类型，不得静默吞掉。

## 8. 数据安全与校验

- 外部数据（API 响应、网页抓取）入库前**必须**做：
  - 字段类型校验（pydantic 或手动类型检查）
  - 按 `id` 字段去重
  - 记录来源和采集时间
- 禁止伪造或猜测 stars、HN points、作者、发布时间等事实字段。
- 无法确认的信息标记 `needs_review`，不得直接发布。

## 9. 日志

- **禁止**裸 `print()`。
- 运行时日志使用标准库 `logging`，按模块获取 logger：`logger = logging.getLogger(__name__)`。
- CLI 输出通过统一的 console/output 封装函数输出。

## 10. 测试

- 单测覆盖率 **≥ 80% branch coverage**（`pytest --cov --cov-branch`）。
- 测试框架：**pytest**，覆盖率插件：**pytest-cov**。
- `tests/` 目录、自动生成的代码（如 protobuf stub）不计入覆盖率分母。
- 覆盖率 < 80% 时 CI **fail**，不做 warn 容忍。
- 对外部网络请求使用 mock 或录制的样例数据，不依赖实时网络。

## 11. CI 验证管线

- CI（GitHub Actions）在 push/PR 到 main 时执行：
  1. `ruff check .` — lint + import 排序检查
  2. `ruff format --check .` — Black 格式检查
  3. `mypy --strict src/` — 类型检查
  4. `pytest --cov --cov-branch --cov-fail-under=80` — 单测 + 覆盖率
  5. `rg "TODO(?!\(#\d+\))" src/` — 未关联 Issue 的 TODO 检查（exit 1 阻断）
- Python 版本矩阵：至少 **3.12**（当前目标版本），后续可扩展 3.11。

## 12. 依赖管理

- 使用 **pyproject.toml** 作为项目元数据和依赖声明文件。
- 依赖管理工具：**uv** 或 **pip-tools**，生成 lock 文件提交到仓库。
- 直接依赖写入 `pyproject.toml` 的 `[project] dependencies`，间接依赖由 lock 文件锁定。

## 13. 禁止事项

- 禁止在业务逻辑代码中使用裸 `assert`（可用 `raise ValueError` 等替代）。
- 禁止使用 `except:` 裸捕获（至少指定 `except Exception`）。
- 禁止在异常处理中静默失败：必须记录错误来源、上下文和可重试信息。
- 禁止 `requirements.txt` 作为唯一依赖声明（必须配合 pyproject.toml）。
- 禁止覆盖或删除 `knowledge/raw/` 中的原始采集记录。
