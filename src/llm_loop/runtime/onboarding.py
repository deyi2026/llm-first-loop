"""One user-facing start action, reusing the existing init/doctor/Web paths."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from llm_loop.runtime.doctor import human_report, inspect_first_use
from llm_loop.runtime.first_use import plan_first_use, run_first_use


def _launch_web(callback: Callable[[], int]) -> int:
    return callback()

def run_start(
    *, args: Any, root: Path, bundle: Path | None,
    environment: Mapping[str, str], check_install: Callable[[], dict[str, Any]],
    preview: bool, as_json: bool, launch_web: Callable[[], int],
    rule_lookup: Callable[[Path, str], bool] | None = None,
) -> int:
    """Explicit start -> existing consent-bound init if needed -> doctor -> Web."""
    if as_json and not preview:
        print("--json 仅能与 --plan 搭配；不能静默启动 Web。", file=sys.stderr)
        return 2
    plan, _ = plan_first_use(args=args, root=root, bundle=bundle, environment=environment)
    if preview:
        result = {
            "schema": "lfl.start.plan/v1",
            "configuration": plan["status"],
            "read_only": True,
            "will_start_web": False,
            "requires_consent": True,
            "next_step": "lfl start" if plan["status"] != "blocked" else "lfl doctor",
        }
        if as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("LFL 首次启动预览：" + result["configuration"] + "。下一步：" + result["next_step"])
        return 1 if plan["status"] == "blocked" else 0

    if plan["status"] == "blocked":
        print("配置目标不可用；请运行 lfl doctor 检查。", file=sys.stderr)
        return 1
    if plan["target"]["can_create"]:
        result = run_first_use(
            args=args, root=root, bundle=bundle, environment=environment,
            check_install=check_install, preview=False, as_json=False,
            rule_lookup=rule_lookup,
        )
        if result != 0:
            return result
    diagnosis = inspect_first_use(
        args=args, root=root, bundle=bundle, environment=environment,
        check_install=check_install, rule_lookup=rule_lookup,
    )
    # Missing context assets degrade the briefing, not the start path; only real
    # configuration/installation problems block Web launch.
    blocking = [c for c in diagnosis["checks"] if c["status"] != "pass" and c["id"] != "context_assets"]
    if blocking:
        print(human_report(diagnosis))
        print("配置尚未就绪；不会启动 Web。按诊断建议修复后重试 lfl start。")
        return 1
    print("LFL 已就绪，启动现有 Web 服务（按 Ctrl+C 结束）。")
    return _launch_web(launch_web)
