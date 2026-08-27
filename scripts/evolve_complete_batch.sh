#!/bin/bash
# 台账登记闭环（2026-08-23 按建议执行）: 12 条已核实落地/排查完成项的 evolve-complete 批量命令
# 用法: bash scripts/evolve_complete_batch.sh（需在主区 .venv 环境，LLM_CLI 入口）
# 说明: evolve-complete 是 CLI 人工通道（AI 的 evolution_complete 仅接受 executing 状态，
#       这些项停在 accepted/executing，需 CLI 标记完成）。每条附结论，可整体执行或逐条删改。
CLI=".venv/bin/python -m llm_loop.cli"

echo "=== 台账登记闭环（12 条已核实落地/排查完成）==="
$CLI evolve-complete EVO-20260823-12be9cac "三层文件事实已落地主区+验证（path_registry/search_files path/read-edit登记/停滞扩展/规则19，smoke test实证+50测试通过）"
$CLI evolve-complete EVO-20260823-adeadd62 "声明提醒可见化已落地主区（role=user）+38测试通过"
$CLI evolve-complete EVO-20260812-2bd55cf3 "记忆双大括号纠错已落地主区（extract.py {{}}→{}）+测试通过"
$CLI evolve-complete EVO-20260811-f1e43351 "测试副作用审计已落地主区（audit脚本+conftest钩子，误报61→3收敛）"
$CLI evolve-complete EVO-20260820-6f552144 "停滞率口径排查完成（detail唯一2093/2093实证，非压缩误判，无需代码）"
$CLI evolve-complete EVO-20260811-db60d36d "测试隔离已落地（test_model_fallback tempfile.mkdtemp实证）"
$CLI evolve-complete EVO-20260816-7b21d0f3 "playwright单exec评估已落地（tools_playwright_exec存在）"
$CLI evolve-complete EVO-20260816-96215428 "playwright门控升级已落地（registry_playwright实证）"
$CLI evolve-complete EVO-20260816-bfb9f215 "playwright_exec主体已落地（工具注册实证）"
$CLI evolve-complete EVO-20260818-f675796c "缓存治理已落地（tool_trim_age/tool_tail实证）"
$CLI evolve-complete EVO-20260812-d8a76517 "MemoryStore外部直写保护已落地（_merge_remote_changes+锁+原子写）"
$CLI evolve-complete EVO-20260815-f22ab8dd "真实tool-call往返门禁已落地（run_real_smoke.sh:61-66实证）"

echo "=== 完成。若某条报'不存在/状态不符'，单独核对后处理 ==="
