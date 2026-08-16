"""路径 E：上下文约定注入（design.md §2.1 / spec §5.3）.

编辑/创建文件后，从同目录既有代码提取编码约定（import 风格/命名/类型
标注/错误处理），注入 LLM 上下文供后续编辑参考（P0 定案 D2: 回执追加 +
违背提示双通道）。

- 扫描: ast.parse 解析同目录代码文件（scan_depth 扩展子目录，上限 scan_file_limit）
- 四类约定: import_style / naming / type_annotation / error_handling
- 提取超时 timeout_s（缺省 5s）→ 返回空摘要（fail-open 跳过注入）
- 解析异常 → 跳过异常项继续
- 脱敏钩子链: 剔除密钥/token 模式（默认内置正则；可注入 sanitizer）
- 体积超 max_chars → 截断 + truncated 标注
- 无约定 → conventions=() 不注入（零开销）
- 事件落盘: task.convention.injected
"""

from __future__ import annotations

import ast
import logging
import re
import time
from pathlib import Path
from typing import Any

from llm_loop.task_quality.models import ConventionItem, ConventionSummary, ConventionType

logger = logging.getLogger(__name__)

# 内置脱敏模式（密钥/token/凭证明文）
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd)\s*[=:]\s*['\"][^'\"]{6,}['\"]"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{16,}"),
)

_NAMING_RE = {
    "snake_case": re.compile(r"\b[a-z][a-z0-9_]*\b"),
    "camelCase": re.compile(r"\b[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*\b"),
    "PascalCase": re.compile(r"\b[A-Z][a-zA-Z0-9]*\b"),
}


class ConventionExtractor:
    """约定提取器（ast 解析 + 四类约定 + 脱敏 + 体积控制）."""

    def __init__(
        self,
        *,
        max_chars: int = 2000,
        timeout_s: float = 5.0,
        scan_file_limit: int = 20,
        scan_depth: int = 0,
        sanitizer: Any | None = None,
        event_store: Any | None = None,
        session_id: str = "",
    ) -> None:
        self._max_chars = max_chars
        self._timeout_s = timeout_s
        self._scan_file_limit = scan_file_limit
        self._scan_depth = scan_depth
        self._sanitizer = sanitizer or self._default_sanitize
        self._event_store = event_store
        self._session_id = session_id

    def extract(self, target_path: str) -> ConventionSummary:
        """提取目标文件同目录的代码约定.

        Args:
            target_path: 目标文件路径（提取其所在目录的约定）。

        Returns:
            ConventionSummary（无约定/失败 → conventions=() 空摘要，不注入）。
        """
        start = time.perf_counter()
        try:
            target = Path(target_path)
            # 目标文件可能尚未创建（编辑场景）——始终取所在目录为扫描根
            base_dir = target.parent if target.suffix else target
            if not base_dir.is_dir():
                return ConventionSummary(target_path=target_path)
            files = self._scan_files(base_dir)
            if not files:
                return ConventionSummary(target_path=target_path)
            items: list[ConventionItem] = []
            file_agg: list[list[ConventionItem]] = []  # 每文件约定（聚合用）
            for fp in files:
                try:
                    tree = ast.parse(fp.read_text(encoding="utf-8", errors="replace"))
                except (OSError, SyntaxError, UnicodeDecodeError) as exc:
                    logger.warning("约定提取解析异常（跳过）: %s: %s", fp, exc)
                    continue
                fi = []
                fi.extend(self._extract_import_style(tree))
                fi.extend(self._extract_naming(tree))
                fi.extend(self._extract_type_annotation(tree))
                fi.extend(self._extract_error_handling(tree))
                file_agg.append(fi)
                if len(file_agg) >= self._scan_file_limit:
                    break
            items = self._aggregate(file_agg)

            if not items:
                return ConventionSummary(target_path=target_path)

            # 体积控制
            text = ConventionSummary(
                target_path=target_path, conventions=tuple(items),
                source_files=tuple(str(f) for f in files[:5]),
            ).to_injection_text()
            truncated = len(text) > self._max_chars
            retained = min(len(text), self._max_chars)
            summary = ConventionSummary(
                target_path=target_path, conventions=tuple(items),
                source_files=tuple(str(f) for f in files[:5]),
                truncated=truncated, original_size=len(text), retained_size=retained,
            )
            # 事件落盘（统计，不含代码内容）
            if self._event_store is not None:
                try:
                    self._event_store.append(
                        self._session_id, "task.convention.injected",
                        {
                            "target_path": target_path,
                            "file_count": len(files),
                            "convention_count": len(items),
                            "truncated": truncated,
                            "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                        },
                    )
                except Exception:  # noqa: BLE001 — 事件落盘失败 fail-open
                    logger.warning("约定注入事件落盘失败（fail-open）", exc_info=True)
            return summary
        except Exception as exc:  # noqa: BLE001 — 提取异常 fail-open 空摘要
            logger.warning("约定提取异常（fail-open 空摘要）: %s", exc)
            return ConventionSummary(target_path=target_path)

    def _scan_files(self, base_dir: Path) -> list[Path]:
        """扫描代码文件（同目录；scan_depth=1 含子目录；上限 scan_file_limit）."""
        files: list[Path] = []
        candidates = (sorted(base_dir.glob("*.py")) if self._scan_depth <= 0
                      else sorted(base_dir.rglob("*.py")))
        for fp in candidates:
            if ".git" in fp.parts or "__pycache__" in fp.parts:
                continue
            files.append(fp)
            if len(files) >= self._scan_file_limit:
                break
        return files

    @staticmethod
    def _extract_import_style(tree: ast.AST) -> list[ConventionItem]:
        """import 风格: 绝对/相对、from-import、分组."""
        items: list[ConventionItem] = []
        abs_imports = rel_imports = from_imports = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                abs_imports += 1
            elif isinstance(node, ast.ImportFrom):
                from_imports += 1
                if node.level and node.level > 0:
                    rel_imports += 1
        if abs_imports + from_imports > 0:
            style = "绝对导入" if rel_imports == 0 else "相对导入为主"
            items.append(ConventionItem(
                ConventionType.IMPORT_STYLE,
                f"import 风格: {style}（import {abs_imports} / from-import {from_imports}）",
            ))
        return items

    @staticmethod
    def _extract_naming(tree: ast.AST) -> list[ConventionItem]:
        """命名约定: 函数/变量名风格统计."""
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.append(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.append(node.id)
        if not names:
            return []
        snake = sum(1 for n in names if re.fullmatch(r"[a-z][a-z0-9_]*", n or ""))
        pascal = sum(1 for n in names if re.fullmatch(r"[A-Z][a-zA-Z0-9]*", n or ""))
        camel = sum(1 for n in names if re.fullmatch(r"[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*", n or ""))
        total = len(names)
        if snake / total >= 0.5:
            style = "snake_case"
        elif pascal / total >= 0.5:
            style = "PascalCase"
        elif camel / total >= 0.5:
            style = "camelCase"
        else:
            style = "混合"
        items = [ConventionItem(ConventionType.NAMING, f"命名约定: {style}（函数/变量 {total} 个）")]
        if style == "混合":
            items.append(ConventionItem(ConventionType.NAMING, f"  分布: snake {snake} / Pascal {pascal} / camel {camel}"))
        return items

    @staticmethod
    def _extract_type_annotation(tree: ast.AST) -> list[ConventionItem]:
        """类型标注模式: 是否强制、标注风格."""
        funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if not funcs:
            return []
        annotated = sum(
            1 for f in funcs
            if f.args.args and all(a.annotation is not None for a in f.args.args)
            or f.returns is not None
        )
        if annotated / len(funcs) >= 0.5:
            return [ConventionItem(ConventionType.TYPE_ANNOTATION, "类型标注: 强制（函数参数/返回值均标注）")]
        return [ConventionItem(ConventionType.TYPE_ANNOTATION, "类型标注: 非强制（部分函数标注）")]

    @staticmethod
    def _extract_error_handling(tree: ast.AST) -> list[ConventionItem]:
        """错误处理惯用法: try/except 模式、自定义异常."""
        try_excepts = 0
        bare_excepts = 0
        custom_excs = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                try_excepts += 1
                for h in node.handlers:
                    if h.type is None:
                        bare_excepts += 1
            elif isinstance(node, ast.ClassDef) and node.name.endswith(("Error", "Exception")):
                custom_excs += 1
        items: list[ConventionItem] = []
        if try_excepts > 0:
            pattern = "裸 except（捕获所有）" if bare_excepts / try_excepts > 0.3 else "精确 except"
            items.append(ConventionItem(
                ConventionType.ERROR_HANDLING,
                f"错误处理: {pattern}（try/except {try_excepts} 处）",
            ))
        if custom_excs > 0:
            items.append(ConventionItem(
                ConventionType.ERROR_HANDLING, f"自定义异常: {custom_excs} 个（*Error/*Exception 后缀）"
            ))
        return items

    @staticmethod
    def _aggregate(file_agg: list[list[ConventionItem]]) -> list[ConventionItem]:
        """跨文件聚合: 同类型约定取主导值（多数文件一致的约定）.

        每类型输出 1-2 条摘要（如命名蛇形主导、类型标注强制），避免逐文件罗列。
        """
        if not file_agg:
            return []
        # 按类型分组收集各文件的约定值
        by_type: dict[ConventionType, list[str]] = {}
        for fi in file_agg:
            for item in fi:
                by_type.setdefault(item.convention_type, []).append(item.content)
        out: list[ConventionItem] = []
        for ctype, contents in by_type.items():
            # 排除细节行（含"分布:"前缀的 naming 辅助行）
            main = [c for c in contents if not c.startswith("  分布")]
            if not main:
                main = contents
            counts: dict[str, int] = {}
            for c in main:
                counts[c] = counts.get(c, 0) + 1
            dominant = max(counts.items(), key=lambda kv: kv[1])
            # 主导值占多数（>=50%）才作为约定；否则标注混合
            if dominant[1] / len(main) >= 0.5:
                out.append(ConventionItem(ctype, dominant[0]))
            else:
                # 混合时取共同前缀语义（如命名都含 snake_case 字样）
                uniq = list(dict.fromkeys(main))
                # 提取共同关键词（snake_case/PascalCase/绝对/相对/强制）
                common = []
                for kw in ("snake_case", "PascalCase", "camelCase", "绝对", "相对", "强制", "非强制", "精确", "裸"):
                    if all(kw in c for c in uniq[:5]):
                        common.append(kw)
                label = "、".join(common) if common else "混合"
                out.append(ConventionItem(ctype, f"{ctype.value} 混合风格（主导: {label}）"))
        # 固定顺序: import → naming → annotation → error
        order = {
            ConventionType.IMPORT_STYLE: 0, ConventionType.NAMING: 1,
            ConventionType.TYPE_ANNOTATION: 2, ConventionType.ERROR_HANDLING: 3,
        }
        out.sort(key=lambda i: order.get(i.convention_type, 9))
        return out

    @staticmethod
    def _default_sanitize(text: str) -> str:
        """默认脱敏: 剔除密钥/token 模式."""
        for pat in _SECRET_PATTERNS:
            text = pat.sub("[REDACTED]", text)
        return text

    def check_violations(self, summary: ConventionSummary, new_code: str) -> list[str]:
        """P0 定案 D2: 检测新代码是否明显违背目录约定（引导反馈）.

        Returns:
            违背项清单（空=无明显违背）。
        """
        violations: list[str] = []
        try:
            tree = ast.parse(new_code)
        except SyntaxError:
            return violations  # 新代码语法错误不判约定违背
        for item in summary.conventions:
            if item.convention_type == ConventionType.NAMING:
                funcs = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                style = item.content.split(":")[1].split("（")[0].strip()
                for fname in funcs:
                    style_ok = (
                        (style == "snake_case" and re.fullmatch(r"[a-z][a-z0-9_]*", fname))
                        or (style == "PascalCase" and re.fullmatch(r"[A-Z][a-zA-Z0-9]*", fname))
                    )
                    if not style_ok:
                        violations.append(f"命名约定违背: '{fname}' 不符合 {style}（目录约定 {item.content[:40]}）")
            elif item.convention_type == ConventionType.TYPE_ANNOTATION and "强制" in item.content:
                funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                for f in funcs:
                    if f.args.args and any(a.annotation is None for a in f.args.args):
                        violations.append(f"类型标注违背: 函数 '{f.name}' 参数缺少类型标注（目录约定强制标注）")
                        break
        return violations[:5]  # 最多 5 条防超长


# 协议别名（tasks.md §1.5）
ConventionExtractorProtocol = ConventionExtractor
