---
title: SemIf（logit_bias 锁 label 读判别概率）在本地 35B 上不可用
scenario: 想用零生成的 logit_bias+logprobs 读判别概率，替代 CoT 做 gate/分类判断
root_cause: 指令式 prompt 在 max_tokens=1 处模型分布质量集中在空白/换行 token，两个 label 都不在 top 候选内；logit_bias 只是加性偏置，无法凭空造出判别信号
solution: "不可行，勿再尝试。实测（mlx_lm server + Ornith-1.5-35B-A3B-MLX）：label id 保留=101780/丢弃=126226，logit_bias={两 label:20} 后 picked 恒为「保留」，p=0.0047（该保留的重启任务）vs 0.0166（该丢弃的天气闲聊）——方向反且无区分度；同位置模型真实首选是空串 p=0.5248 / 换行 p=0.7777，说明该位置模型本就不打算出词。chat 端点更差，max_tokens=1 首 token 恒为「用户」(id 97237)。可行部分：请求级 logit_bias 确实生效（server.py:1801），top_logprobs 支持 0-11，label id 用 transformers.AutoTokenizer.from_pretrained(本地模型目录) 取（mlx_lm 无 load_tokenizer，只有 utils.load）。"
evidence: 2026-09-22 本机 8901 实测脚本输出：picked='保留' p=0.0047 / p=0.0166；top_logprobs 显示 '' 0.5248、'\n\n' 0.7777
tags: [semif, logit_bias, mlx-lm, gate, negative-result]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-22T06:13:36.335987+08:00"
updated_at: "2026-09-22T06:13:36.335987+08:00"
---