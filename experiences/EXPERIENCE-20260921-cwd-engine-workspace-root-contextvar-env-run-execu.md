---
title: 引擎沙箱 cwd 由 engine.workspace_root 决定：外层 contextvar/env 均会被 run 入口覆盖，模型可借 execute_command 逃逸改写评估夹具
scenario: "hev0 P3 Stage-A 二跑（run 012806Z）：t4/t5 的 b1（引擎臂）行模型经 execute_command 逃逸出 temp 沙箱，把任务完成产物直接写进任务源目录（t4 done/{d,e,f}+oplog、t5 new.cfg），污染后续所有 run 的夹具与判分（G4 t4-partial 臂变 1.0 拦截）。定位过程三次假设三次被证伪：外层 contextvar 绑定（被 lifecycle 覆盖）、LFL_RUNTIME_ROOT/LFL_WORKSPACE_ROOT env（不进该决策链）、进程 cwd 回落（工具实际 cwd 与进程 cwd 不符）。最终量测锁定：engine.workspace_root 在装配时已被赋仓库根，engine.run 经 lifecycle._bound_run_context 每 run 把 current_workspace_root 绑为该字段，工具相对路径/命令 cwd 全部跟随。"
root_cause: ""
solution: "1) 污染取证先做 mtime 指纹（文件 mtime vs 行执行窗口吻合=定罪），再看引擎行自己的 change_log（模型实际执行的命令+解析路径全在里面）；2) 逐层量测而非逐层猜测：probe 直接 print engine.workspace_root 实际值（零 LLM 成本）即可终结三层假设争论；3) 修复锚定引擎自文档化扩展字段 engine.workspace_root=str(workdir)（engine.py:297-299 注明该字段供 run 入口注入 contextvar 跟随工具 cwd），一次调用后用\"pwd>文件\"法验证文件系统副作用落在沙箱；4) 纵深防御：run_ab --execute 材料化每 run 冻结任务副本并 chmod 只读，即便模型再逃逸也写不进任务面；5) 夹具恢复用污染前归档做字节级还原（本例 oplog 原文三行来自 012806Z t4::b1 行自己的 ws_archive——它拷贝于污染发生前），恢复后跑 oracle 自检臂复验（t4-partial→0.0, t5 pristine→0.0）。"
evidence: "012806Z t4::b1 行 change_log（09:30:24 find $W=evals/.../tasks/t4_resume_oplog/workspace + 09:30:29/36/44 cp/printf 改写源）；源文件 mtime=09:30:29-44 与行执行窗口精确吻合；tasks/t5_resume_partial_edit/workspace/new.cfg mtime=09:32:25（t5::b1 窗口）；G4 拦截 t4-partial fail_arm=1.0；probe5 文件证据（pwd>cwd_proof.txt 落仓库根，模型命令无 cd）；probe6 量测 engine.workspace_root=仓库根（cwd/env 均已正确指向 ws）；修复验证 probe7（engine.workspace_root=ws → 文件落 ws，FIX VERIFIED）；lifecycle.py:137/156 run_workspace=self.workspace_root；engine.py:297-299 字段自文档"
tags: [sandbox-escape, engine-workspace-root, execute_command, contextvar-override, fixture-pollution, mtime-forensics, hev0, defense-in-depth]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-21T09:55:40.835235+08:00"
updated_at: "2026-09-21T09:55:40.835235+08:00"
---

沙箱隔离的正确性证明不能只看"进程 cwd 正确"——工具的 cwd 决策链可能有三层（contextvar 绑定 → 引擎字段 → os.getcwd 回落），且引擎会用自己的字段覆盖外层绑定。验证必须落在最外层真实缝（engine.run 全链 + 文件系统副作用证据），直调 registry.execute 验证的只是最内层。附带发现：G4 的"判分器自检臂红"可能是夹具被污染的正确报警——判分器没问题，是夹具源被上一轮逃逸行改写了；恢复夹具前先查 mtime 指纹定位污染窗口。