#!/usr/bin/env python3
"""EVO 编号机械检查：把「引用的演进编号必须真实存在」变成可执行的门禁。

背景：仓库里出现过在注释中写下「看起来可核验」的演进编号、而演进记录
里根本不存在对应条目的凭空编造引用。本脚本扫描指定文本，提取全部
EVO 引用，与演进建议记录（JSONL 真值源）中的已知编号比对，报告未知
引用。

退出码约定：
  0 —— 通过：所有引用均可回溯；或真值源缺失且显式给了 --allow-missing
  1 —— 有结论地失败：存在未知 EVO 引用（stdout 逐条列出 文件:编号）
  2 —— 无法判定：真值源缺失/不可读/格式损坏，或输入路径不存在

当前定位（2026-11-02 复测）：
  `.venv/bin/python scripts/check_evo_refs.py src docs scripts tests`
  → scanned=4174 files, distinct_refs=225, known=237（滚动窗口）,
    history=167（提交信息里出现过的编号）, 窗口外真编号=95, 未知=154。
  两道补充真值都补不全：演进记录是**滚动窗口**，提交信息只覆盖部分历史。
  因此引入 **baseline 豁免表**（scripts/evo_refs_baseline.json，append-only）：
  现存无法回溯的历史编号一次性登记，之后只拦**新增**的编造引用。
    --regen-baseline  重新登记当前未知编号（一次性、需人工审阅 diff）
  有了 baseline 才可作 CI 硬门禁：新旧编号都过不了 baseline 才 DENIED。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER_REL = "data/audit/evolution_suggestions.jsonl"

# 引用语法固定为紧凑日期写法：8 位日期 + 连字符 + 8 位小写十六进制。
# 无词边界、子串语义：宁可多报（交由人工复核），不可漏报编造引用。
REF_PATTERN = re.compile(r"EVO-\d{8}-[0-9a-f]{8}")
# 真值源历史数据中存在带横线的日期写法（EVO-YYYY-MM-DD-哈希）；归一化为
# 紧凑写法后并入已知集合，避免同一条记录因书写格式不同而被误报为未知。
DASHED_ID_PATTERN = re.compile(r"^EVO-(\d{4})-(\d{2})-(\d{2})-([0-9a-f]{8})$")
# 真值源每行一个 JSON 对象，编号字段以 id 为主、suggestion_id 为兼容别名
ID_FIELDS: tuple[str, ...] = ("id", "suggestion_id")
# 目录输入按文本后缀白名单递归；其余后缀一律跳过，不做编码语义猜测
TEXT_SUFFIXES = frozenset(
    {".py", ".md", ".txt", ".rst", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".sh"}
)


class LedgerFormatError(ValueError):
    """真值源格式损坏：宁可「无法判定」，不可把坏数据当作空集合放行。"""


def extract_refs(texts: Iterable[str]) -> set[str]:
    """从若干段文本提取全部 EVO 引用，返回去重集合（纯函数）。"""
    refs: set[str] = set()
    for text in texts:
        refs.update(REF_PATTERN.findall(text))
    return refs


def normalize_known_id(raw: str) -> str:
    """归一化真值源编号：带横线日期写法折叠为紧凑写法，其余原样保留。"""
    match = DASHED_ID_PATTERN.match(raw.strip())
    if match:
        year, month, day, digest = match.groups()
        return f"EVO-{year}{month}{day}-{digest}"
    return raw.strip()


def known_ids_from_jsonl(path: Path) -> set[str]:
    """读取 JSONL 真值源，返回已知编号集合（已归一化）。

    行缺失编号字段时跳过（真值源允许承载无编号的辅助记录）；行不是
    JSON 对象或解析失败时抛 LedgerFormatError，由 CLI 翻译为退出码 2。
    文件缺失/不可读以 OSError 直通，同样由 CLI 翻译为退出码 2。
    """
    text = path.read_text(encoding="utf-8")
    known: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LedgerFormatError(f"{path}:{lineno}: 行不是合法 JSON（{exc}）") from exc
        if not isinstance(row, dict):
            raise LedgerFormatError(f"{path}:{lineno}: 行不是 JSON 对象")
        for field in ID_FIELDS:
            value = row.get(field)
            if isinstance(value, str) and value.strip():
                known.add(normalize_known_id(value))
    return known


def unknown_refs(texts_by_source: Mapping[str, str], known: set[str]) -> dict[str, set[str]]:
    """求各来源中未被真值源收录的引用（纯函数）。

    返回「来源标签 -> 未知编号集合」；仅包含确有未知引用的来源，便于
    CLI 逐条打印 文件:编号。
    """
    result: dict[str, set[str]] = {}
    for source, text in texts_by_source.items():
        missing = extract_refs([text]) - known
        if missing:
            result[source] = missing
    return result


def history_refs_from_text(blob: str) -> set[str]:
    """从 git log 正文提取历史上真实出现过的编号（纯函数，便于注入测试）."""
    return extract_refs([blob])


def git_history_refs(root: Path) -> set[str] | None:
    """读仓库全部提交信息里的 EVO 编号。

    演进记录是滚动窗口，历史编号会掉出窗口但仍真实存在过——提交信息是
    那些编号的原始出处，故并入可回溯集合，避免把"窗口外的真编号"报成编造。
    git 不可用/不是仓库/超时一律返回 None：**不冒充空集**，由 CLI 如实降级。
    """
    try:
        proc = subprocess.run(
            ("git", "log", "--all", "--no-color", "--format=%B"),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return history_refs_from_text(proc.stdout)


def is_future_dated(ref: str, today: date | None = None) -> bool:
    """编号日期晚于今天 → 不可能是历史欠账，属编造/占位形状，不纳入豁免.

    2026-11-02 实证：一次 `--regen-baseline` 全仓登记时，把测试哨兵
    （形如 EVO-<未来日期>-<8位十六进制>）也当成"历史欠账"豁免掉，
    于是原本用来证明"未知必须被拦"的用例直接失效。未来日期是硬信号。
    """
    match = REF_PATTERN.search(ref)
    if match is None:
        return False
    digits = match.group(0).split("-")[1]
    try:
        stamp = date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))
    except ValueError:
        return False
    return stamp > (today or date.today())


def load_baseline(path: Path) -> set[str]:
    """读豁免表。缺失=空表（干净检出常态）；损坏=告警+空表，绝不静默全豁免."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except (OSError, json.JSONDecodeError) as exc:
        print(f"evo-refs WARNING: 豁免表不可读，按空表处理: {exc}", file=sys.stderr)
        return set()
    exempt = data.get("exempt") if isinstance(data, dict) else None
    if not isinstance(exempt, list):
        print("evo-refs WARNING: 豁免表格式异常，按空表处理", file=sys.stderr)
        return set()
    # 注意：不动大小写。extract_refs 产出的十六进制后缀是小写，曾经 upper() 过
    # 一次，导致豁免表 100% 不命中（"登记了仍报未知"），此处保持原样比对。
    return {str(item).strip() for item in exempt if str(item).strip()}


def collect_text_files(paths: Iterable[Path]) -> list[Path]:
    """展开输入路径：文件直接收录；目录按后缀白名单递归并跳过隐藏目录。"""
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            for candidate in sorted(path.rglob("*")):
                rel_parts = candidate.relative_to(path).parts
                # 跳过 .git/.venv 等隐藏目录，避免噪音与巨量扫描
                if any(part.startswith(".") for part in rel_parts):
                    continue
                if candidate.is_file() and candidate.suffix.lower() in TEXT_SUFFIXES:
                    files.append(candidate)
        else:
            files.append(path)
    return sorted(dict.fromkeys(files))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="待扫描的文件或目录（目录按文本后缀白名单递归）",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=ROOT / DEFAULT_LEDGER_REL,
        help="演进记录真值源（JSONL）路径，默认为仓库内运行期数据文件",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="真值源缺失时降级放行（退出码 0）：仅供干净检出/CI 等无运行期数据的场景",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="只按演进记录判定，不并入 git 历史提交信息（默认并入：窗口外真编号不算未知）",
    )
    parser.add_argument(
        "--baseline",
        default=ROOT / "scripts" / "evo_refs_baseline.json",
        help="豁免表（append-only）：现存无法回溯的历史编号，登记后只拦新增编造引用",
    )
    parser.add_argument(
        "--regen-baseline",
        action="store_true",
        help="把当前无法回溯的编号写入豁免表（一次性；请审阅 diff 后再提交）",
    )
    args = parser.parse_args(argv)
    # 命令行传 string、默认值是 Path：统一成 Path，否则写入时 AttributeError（实测过）。
    baseline_path = Path(args.baseline)

    # 输入路径不存在 → 无法判定（2）：绝不把「扫不到」当作「通过」
    absent = [p for p in args.paths if not p.exists()]
    for path in absent:
        print(f"evo-refs ERROR: 输入路径不存在: {path}", file=sys.stderr)
    if absent:
        return 2

    try:
        known = known_ids_from_jsonl(args.ledger)
    except LedgerFormatError as exc:
        print(f"evo-refs ERROR: 真值源格式损坏，无法判定: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # data/ 是运行期数据且不入库：干净检出时真值源缺失不是失败，而是
        # 「本轮无真值可判」；默认以退出码 2 如实上报，不冒充通过。
        print(f"evo-refs WARNING: 演进记录文件缺失或不可读，本轮无法判定: {exc}", file=sys.stderr)
        print("evo-refs status=unknown reason=ledger_missing")
        if args.allow_missing:
            print("evo-refs: --allow-missing 生效，降级放行（exit 0）；引用未与真值源比对")
            return 0
        return 2

    texts: dict[str, str] = {}
    unreadable: list[str] = []
    for path in collect_text_files(args.paths):
        try:
            texts[path.as_posix()] = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            unreadable.append(f"{path}: {exc}")
    for line in unreadable:
        print(f"evo-refs ERROR: 待扫描文件不可读，无法判定: {line}", file=sys.stderr)
    if unreadable:
        return 2

    # 演进记录是滚动窗口：窗口外的真编号由 git 提交信息回溯（原始出处）。
    history: set[str] | None = None
    if not args.no_history:
        history = git_history_refs(ROOT)
        if history is None:
            print(
                "evo-refs WARNING: 读不到 git 历史，本轮只按演进记录判定"
                "（窗口外真编号可能被误报为未知）",
                file=sys.stderr,
            )
    attested = known if history is None else known | history

    all_refs = extract_refs(texts.values())
    if args.regen_baseline:
        candidates = sorted(all_refs - attested)
        unresolved = [ref for ref in candidates if not is_future_dated(ref)]
        skipped = len(candidates) - len(unresolved)
        payload = {
            "_comment": (
                "EVO 编号豁免表（append-only）：登记时无法回溯的历史编号。"
                "只允许新增条目用于历史欠账；新增代码里的编号必须能回溯到演进记录或提交信息。"
            ),
            "exempt": unresolved,
        }
        try:
            baseline_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            print(f"evo-refs ERROR: 豁免表写入失败: {exc}", file=sys.stderr)
            return 2
        print(f"evo-refs: 已登记豁免 {len(unresolved)} 个编号 → {baseline_path}")
        if skipped:
            print(
                f"evo-refs: 跳过 {skipped} 个未来日期编号（不可能是历史欠账，仍会被拦）",
                file=sys.stderr,
            )
        return 0
    baseline = load_baseline(baseline_path)
    attested |= baseline

    unknown = unknown_refs(texts, attested)
    outside_window = len(all_refs - known)
    print(
        f"evo-refs: scanned={len(texts)} files, "
        f"distinct_refs={len(all_refs)}, known={len(known)}, "
        f"history={len(history) if history is not None else 'unavailable'}, "
        f"窗口外真编号={outside_window if history is not None else 'n/a'}, "
        f"exempt={len(baseline & all_refs)}"
    )
    if unknown:
        for source in sorted(unknown):
            for ref in sorted(unknown[source]):
                print(f"BLOCK UNKNOWN: {source}:{ref}")
        print("evo-refs DENIED: 存在既不在演进记录、也不在任何提交信息中的 EVO 引用", file=sys.stderr)
        return 1
    print("evo-refs: PASS（全部 EVO 引用均可回溯到演进记录或提交信息）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
