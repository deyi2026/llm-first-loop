# Phase6 M3 度量验收（T1/T2/T3）

- T1 sync_window_poll：n=10，P50=44.8ms（门≤100，基线 B1=859.3），P95=53.0ms（门≤200）→ PASS
- T2 窗口内 Stop：n=10，P50=30.7ms（门≤100，基线 B2=915.3），四态取消语义断言通过 → PASS
- T3 零语义降级：S1/S2/S3/S7/S8/S9/W3 单测锁定；全量回归门=M4 → PASS

样本明细见 M3_ACCEPTANCE.json；场景=同步通道窗口内打断（fake 窗口 1.2s，t+0.3s 注入/取消）。
