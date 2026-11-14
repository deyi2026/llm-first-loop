"""DESIGN-20261114（Deepin P0）: host_access_request 装配注册冒烟.

factory 装配函数（与 escalation_request 同路径）import 即验证注册链无语法/
循环依赖问题；工具行为由 test_host_grant_closure/web/e2e 覆盖。
"""
from __future__ import annotations

import importlib


def test_host_access_tool_importable_and_factory_registration_wired():
    mod = importlib.import_module("llm_loop.factory")
    assert hasattr(mod, "EscalationRequestTool")
    tool_mod = importlib.import_module("llm_loop.tools.builtin.host_access")
    assert hasattr(tool_mod, "HostAccessRequestTool")
    with open(mod.__file__, encoding="utf-8") as fh:
        src = fh.read()
    assert 'from llm_loop.tools.builtin.host_access import HostAccessRequestTool' in src
    assert '_register_basic("host_access_request", HostAccessRequestTool(' in src
