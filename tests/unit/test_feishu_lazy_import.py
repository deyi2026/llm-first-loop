"""Pure Feishu control modules must not require the SDK at package import time."""

import os
import subprocess
import sys
from pathlib import Path


def test_feishu_package_and_restart_guard_import_without_lark_sdk() -> None:
    root = Path(__file__).resolve().parents[2]
    code = """
import builtins
real_import = builtins.__import__
def guarded(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'lark_oapi' or name.startswith('lark_oapi.'):
        raise ImportError('simulated missing lark_oapi')
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = guarded
import llm_loop.feishu
import llm_loop.feishu.restart_guard
print('PURE_FEISHU_IMPORT_OK')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "PURE_FEISHU_IMPORT_OK" in proc.stdout
