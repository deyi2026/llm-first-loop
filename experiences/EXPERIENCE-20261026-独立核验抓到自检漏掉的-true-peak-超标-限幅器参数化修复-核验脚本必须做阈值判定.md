---
title: 独立核验抓到自检漏掉的 True Peak 超标：限幅器参数化修复 + 核验脚本必须做阈值判定
scenario: "视频成片交付前的独立核验中，审查子代理（glm-5.3，1M 上下文）测出 v2 的 True Peak = -1.4 dBFS，超出 -1.5 dBTP 上限 0.1 dB。这个缺陷我自己在 verify_v2.py 的自检中没有发现——因为该脚本只打印 ebur128 的输出，没有做阈值判定。同时它还诚实报告\"核验期间文件被外部进程改写\"，指出其结论只对当时快照有效。"
root_cause: 验收脚本只打印测量值不做阈值判定，导致超标的 True Peak 漏检；根因是合成链路的限幅阈值与 loudnorm 的 TP 目标不自洽。
solution: |
  1) 根因定位：共享合成链路 `fc.append("[amixin]" + ln + ",alimiter=limit=0.95:level=0[aout]")` 中，limit=0.95 相当于 -0.45 dBFS，放行远高于 loudnorm 的 TP=-1.5 目标，叠加 AAC 编码过冲后真峰值超标。2) 修复方式（保真优先）：把 assemble.py 的 build() 增加 loud_i/loud_tp/limiter 三个参数，**默认值保持 v1 行为完全不变**（RULE-AI-24 先保真再优化），v2 单独传 loud_tp=-1.8、limiter=0.80；复测 TP 从 -1.4 降到 -1.9 dBFS，积分响度仍为 -16.0 LUFS。3) 方法论：核验脚本必须做**阈值判定并给出 PASS/FAIL**，不能只打印数值；本任务中自检脚本只打印不判定，所以漏掉了超标。4) 并行风险：子代理核验期间主会话继续重新生成交付物，会让核验结论失效（它自己也点出了这一点）。正确做法是冻结交付物后再启动核验，或核验后对最终版本重跑一遍确认——本任务采用后者，最终 13/13 字幕一致性与响度均复测通过。
  
  当前性验证：跑 `cd $HOME/lfl-workspace/work/psa-video-1min && ffmpeg -hide_banner -i 05_final/final_v2.mp4 -af ebur128=peak=true -f null - 2>&1 | grep -E "I:|Peak:"` 应得 I=-16.0 LUFS、Peak=-1.9 dBFS（若得 Peak=-1.4 说明修复未生效）；另跑 `grep -n "loud_tp\|limiter" 04_tools/assemble.py 04_tools/assemble_v2.py` 应能看到 build() 已参数化且 v2 传入了 loud_tp=-1.8 / limiter=0.80。
evidence: 工具实测：独立核验子代理（glm-5.3）报告 v2 TP=-1.4dBFS 超 -1.5 上限、v1 恰为 -1.5 达标；修复后 ffmpeg ebur128 复测 final_v2.mp4 与 final_nomusic.mp4 均为 I=-16.0 LUFS / TP=-1.9 dBFS / LRA 4.0 与 6.4。
tags: [视频, 响度, 真峰值, 独立核验, 交付验收]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-26T20:48:28.793423+08:00"
updated_at: "2026-10-26T20:48:28.793423+08:00"
---