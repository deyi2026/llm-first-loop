"""飞书桥启动入口（python -m llm_loop.feishu）.

`-m` 执行包需本文件（__init__.py 内的 __main__ 块不参与包入口）。
"""

from llm_loop.feishu import main

if __name__ == "__main__":
    main()
