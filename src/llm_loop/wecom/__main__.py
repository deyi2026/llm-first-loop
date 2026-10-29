"""企微桥启动入口（以 -m 方式执行 llm_loop.wecom）.

`-m` 执行包需本文件（__init__.py 内的 __main__ 块不参与包入口）；
runtime.launch 经 runpy.run_module("llm_loop.wecom", run_name="__main__")
同样执行到本文件的 main()（与飞书 __main__.py 写法一致）。
"""

from llm_loop.wecom import main

if __name__ == "__main__":
    main()
