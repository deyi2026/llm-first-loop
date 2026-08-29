"""统一服务启动入口（RUNTIME-SOT-WIRE R2）。

用法：
  python -m llm_loop.runtime.launch web   [--model X] [--port N]
  python -m llm_loop.runtime.launch feishu [--model X]
  python -m llm_loop.runtime.launch web --dry-run   # 只打印 effective 配置

shell 脚本（restart_system.sh/restart_mirror.sh）只负责进程管理（stop/PID/nohup/日志）；
业务配置语义全部在此解析（resolver → identity 守卫 → 服务入口）。
"""
from __future__ import annotations

import argparse
import runpy
import sys

from .identity import check_identity
from .manifest import build_manifest, write_manifest
from .resolver import apply_to_environ, resolve_effective

_SERVICES = {
    "web": "llm_loop.web",
    "feishu": "llm_loop.feishu",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="llm_loop.runtime.launch")
    parser.add_argument("service", choices=sorted(_SERVICES))
    parser.add_argument("--model", help="显式 model override（最高优先级，被记录）")
    parser.add_argument("--port", help="显式端口 override")
    parser.add_argument("--dry-run", action="store_true", help="只打印 effective 配置，不启动服务")
    args = parser.parse_args(argv)

    cli: dict[str, str] = {}
    if args.model:
        cli["LLM_MODEL"] = args.model
    if args.port:
        cli["WEB_PORT"] = args.port

    # 启动守卫（R1）：shadow 记录 / enforce 拒绝
    report = check_identity()

    ec = resolve_effective(args.service, cli)
    print(f"[runtime-launch] service={args.service} identity_ok={report.ok} "
          f"workspace={ec.workspace_root} env_file={ec.env_file}", file=sys.stderr)
    if ec.ignored_shell_env:
        print(f"[runtime-launch] ignored shell env (not authoritative): "
              f"{sorted(ec.ignored_shell_env)}", file=sys.stderr)

    if args.dry_run:
        import json
        print(json.dumps(ec.to_summary(), ensure_ascii=False, indent=2))
        # R3: dry-run 同步预览将写入的 manifest（不落盘，仅展示）
        print(json.dumps(build_manifest(args.service, ec, report),
                         ensure_ascii=False, indent=2))
        return 0

    apply_to_environ(ec)
    # R3: 启动即写 manifest（身份 + 配置指纹 + providers 三 hash 的唯一事实源）
    manifest = build_manifest(args.service, ec, report)
    mf_path = write_manifest(manifest, report.data_dir)
    print(f"[runtime-launch] manifest: {mf_path} "
          f"config_hash={manifest['config_hash'][:12]}", file=sys.stderr)
    runpy.run_module(_SERVICES[args.service], run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
