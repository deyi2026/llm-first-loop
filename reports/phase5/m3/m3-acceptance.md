# Phase5 M3 度量验收（G1/G2）

- G1 llm_stream_interrupt：n=10，P50=39.6ms（门≤500），P95=115.8ms（门≤900）→ PASS
- G2 llm_stream 保守（开关关闭）：n=10，P50=1004.4ms（门≤1550）→ PASS

样本明细见 M3_ACCEPTANCE.json；场景形态=S17-M1/M4（确定性注入钩子）。
