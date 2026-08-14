"""D1 事件源化 / 单一真相源（event_log）.

- model.py: Event 对象 + 序列化/解析纯函数 + 事件类型登记表
- store.py: EventStore（append-only 落盘 data/event_logs/<session_id>.jsonl）
- replay.py: replay_session（事件 → 派生视图）
- reconcile.py: reconcile（重放视图 vs 源逐字段比对）
- inventory.py: run_inventory（三套存储只读盘点）
- migrate.py: run_migration / run_rollback（存量迁移与回滚编排）
"""

from __future__ import annotations
