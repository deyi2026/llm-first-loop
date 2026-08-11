"""飞书桥 -m 启动入口测试（M42 修复：python -m llm_loop.feishu 需 __main__.py）.

包作为 -m 执行入口需 package/__main__.py；__init__.py 内的 __main__ 块不参与包入口。
"""


def test_feishu_main_entry():
    """__main__.py 存在且暴露 main（python -m llm_loop.feishu 可执行入口）."""
    import llm_loop.feishu.__main__ as feishu_main

    assert hasattr(feishu_main, "main")
    assert callable(feishu_main.main)


def test_feishu_init_main_guard():
    """__init__.py 保留 __main__ 守卫（python llm_loop/feishu/__init__.py 直跑兼容）."""
    import llm_loop.feishu as feishu_pkg

    assert hasattr(feishu_pkg, "main")
    assert callable(feishu_pkg.main)
