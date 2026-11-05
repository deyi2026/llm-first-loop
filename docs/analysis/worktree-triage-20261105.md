# Worktree 清理清单（2026-11-05）

## 已完成（本轮已删，48 棵）

| 类别 | 数量 | 说明 |
|---|---|---|
| `.worktrees` 干净且无独立提交 | 31 | 直接删 |
| `.worktrees` 改动已在 main 等价存在 | 13 | 逐文件核对内容一致后删 |
| `/private/tmp` probe（detached HEAD） | 3 | 已建 `refs/archive/probe-*` + 24 个补丁落盘后删 |
| 项目外干净树 | 1 | 直接删 |

运行数据（`data/audit`、`e2e`、`observability`）已归档到 `.backup/worktree-archive-20261105/`。

## 待你判：有未入 main 的提交（47 棵）

| # | 树 | ahead | 脏文件 | 最近提交 |
|---|---|---|---|---|
| 1 | `.releases/5747b28e62c4d5f6694cb054da77eae126f296b3` | 57 | 0 | fix(web): preserve assurance isolation at opt-in review-plan bootstrap |
| 2 | `.releases/0b2750783ef83a849c7c59aac63c03a21a0a2fe3` | 42 | 0 | fix(gate-scripts): 全量对账脚本 fail-open 堵死（审查 P1-1）+ 三处健壮性 |
| 3 | `.releases/f2ca262ddbfdce60a7373a3e8ce6e00608656a3c` | 37 | 0 | guard(r9): 三项流程摩擦收敛——守卫失败带口径、豁免表只许减、缺参回执一次给全 |
| 4 | `.releases/cc64645a9573a28cb3ff40aec32c3d1394b5c116` | 36 | 0 | feat(service-control): 回执自证核验 + in_flight 已等价判据 + EVO 引用可回溯 |
| 5 | `.releases/1d424c6ffbd83280aca4dc198019538a8c2dff68` | 34 | 0 | feat(status): targets 视图暴露非终态动作 in_flight，一行一动作折叠 restart all |
| 6 | `.releases/4cf96625253e02b2898046124b7c43df62f994f6` | 32 | 0 | guard(r9): full_test 材料投影解准入规模死锁 + 函数行数基线重登记 |
| 7 | `.releases/924dbbea3ba56a7a9475f00643f160788e0730f8` | 31 | 0 | fix(review-gate): 切片外绑定改为 HEAD + 改动集内容，去掉仓库规模依赖 |
| 8 | `.releases/cbfce4a9317ea5ffb331d5ec7a19d5ecd8834b27` | 28 | 0 | fix(review): 越界摘要绑内容而非名字，PASS 回执披露授权面（独立审查 P1×2/P2×2 + 建议 S1/S4/S5） |
| 9 | `.releases/65fc79eb711abf70161b9c9dc0360854aef9622e` | 27 | 0 | fix(review-gate): 切片审查不得背书整树执行，并补 4 项回执口径 |
| 10 | `.releases/5beba5fe7d4998030d4e01d864e7a975f66b4ed7` | 26 | 0 | guard(r9): EVO-20261101-9a6be8b1 审查闸可用性与成本六项 |
| 11 | `.releases/d85c16bb61eb66d563ac7dad6907594521929998` | 25 | 0 | guard(r9): 六项流程摩擦优化（棘轮净零置换 / 孤儿树清单 / phase 产物出树 / 延迟生效待办 / 账本漏行诊断） |
| 12 | `.releases/a204a22f6e64a170a56ed1aaf6a520404ab5a95f` | 24 | 0 | chore(reports): 全量测试重生成的 phase 报告快照（发布前收敛 tracked 树） |
| 13 | `.releases/4fba59da5ebeac884505fc69f698ea638e2115aa` | 19 | 0 | polish(review): 报告目录 0700、fd 泄漏面收口、P10 不再误判为 P1 |
| 14 | `.releases/9ddf748ce4f614f277e5bc5715fd59afac2d6c9a` | 17 | 0 | feat(review): 审查准入非 PASS 时落盘 reviewer 全文与 findings 摘要 |
| 15 | `.releases/cecb8403bdb0c7d373b88897961239cc19ceede2` | 16 | 0 | fix(guard): 收口 task_* 跨会话声明面与归属放行留痕（独立审查 P2-1/P2-2/P2-3 相应处置） |
| 16 | `.worktrees/p1-publish-20261030` | 15 | 0 | docs(write-scope): 交付说明推进到 gen 348（第十四轮已发布、restart 已受理未生效、推送仍未推） |
| 17 | `.releases/88ba2d6c88b3cd86b13c77d32e7af372a69a8861` | 14 | 0 | fix(write-scope): 第十四轮 —— sed/ed 带地址的写面、sed 独立 e 命令、载体簇判定回退 |
| 18 | `.releases/8e1c65234cc4825e13c76d93be17c275e2f7e22f` | 14 | 0 | guard(r9): 五优化（status视图/并发重启判据/日志轮转降噪/命令闸文档/失败覆盖标注）+ 函数规模基线重登记 |
| 19 | `.releases/f47b923d438cd2fdf0feddfe10e126c3ff60c4cf` | 13 | 0 | knowledge: 运行时结算将 legacy remote 经验卡置 invalid（提交以恢复 tracked 干净树供部署） |
| 20 | `.worktrees/lfl-integration` | 13 | 1 | fix(web/model-admin): 整包替换同样保护承载默认的模型，堵 PUT 批量后门 |
| 21 | `.releases/219f988523d4766536c89cacbca4704d557edf3e` | 11 | 0 | fix(write-scope): 第十三轮 —— 短选项簇粘连值、载体 chdir 短簇、rsync 备份写面 |
| 22 | `.releases/2018a45e282dffd5a7db0b7f27bc4654af4a8ed8` | 9 | 0 | fix(write-scope): 第十二轮 —— 粘连文件名、长选项唯一前缀、tar 值选项/exec 载荷、find 元数 |
| 23 | `.worktrees/evo-e0bff8ee-p2-int-20261025` | 9 | 2 | guard(r9): 棘轮补规则 e（legacy 只收 >300 存量），关闭小函数抬巨值脱锚通道 |
| 24 | `.releases/cff9339d42bb1234a093d3b195c17f3205f9f779` | 5 | 0 | Merge branch 'main' into fix/web-v2-ux-hardening-20261013 |
| 25 | `.releases/c9a82d28d496080c9ae7f4fd7399d5a214ffc600` | 4 | 0 | fix(webui): clarify navigation and history loading on desktop and mobi |
| 26 | `.releases/f123e2e69` | 4 | 0 | fix(wecom): 连接前强制企微端点直连，修系统代理劫持 WS 连接（实测复现） |
| 27 | `.releases/6e21e601215bafddffb5feafc6f1af46cc245da3` | 3 | 0 | merge: main cee7fec38（MiniMax H3）并入安全批次基线——无冲突（merge-tree 预检 0 冲突） |
| 28 | `.worktrees/lfl-child-subagent_7c07e3e82414` | 3 | 2 | merge: 企微智能机器人桥 M0 成果并入工作分支 |
| 29 | `.worktrees/lfl-child-subagent_8535491073e7` | 3 | 2 | merge: 企微智能机器人桥 M0 成果并入工作分支 |
| 30 | `.releases/cde11eea1c26eb51171ab0ff6c5b8d19df9b3acb` | 2 | 0 | fix(r9): preserve qualified IO waits for isolated budget transports |
| 31 | `.worktrees/kstore` | 2 | 18 | feat(eval): 跑批知识库绑定隔离（--knowledge-store snapshot/empty/production） |
| 32 | `.releases/5786fc5c95b380393e597e8640a3ccd3f3206cd2` | 1 | 0 | fix(webui): deploy scrollable responsive admin panels from gen257 |
| 33 | `.releases/79ddb8522dc8e1353ad5a4d0e30010ea45dd1dfd` | 1 | 0 | docs(write-scope): gen 345 发布范围与依据——候选 d94b6ce39 审查 REVISE 处置 + 改以 mai |
| 34 | `.releases/ef97f49ae6fbb1b726619db24419f39df9a6db2a` | 1 | 0 | fix(r9): isolate Web budget API auth with existing P2-B type repair |
| 35 | `.worktrees/browser-receipt-reason-20261030` | 1 | 0 | fix(browser): §11.6 P2 双修复——compact 拒因全类提升 + 候选 extras 补 frame_token |
| 36 | `.worktrees/evo-4c041655` | 1 | 0 | fix(admission): 模板文件名放行+内容复核，解除 .env.example 准入死锁 |
| 37 | `.worktrees/evo-rebase-check` | 1 | 0 | fix(admission): 模板文件名放行+内容复核，解除 .env.example 准入死锁 |
| 38 | `.worktrees/lfl-child-subagent_1f9ee85d2718` | 1 | 1 | feat(webui/model-admin): 配置事实/运行事实分离，PATCH 启停与模型级 CRUD |
| 39 | `.worktrees/lfl-child-subagent_2e8b482d1a4d` | 1 | 1 | feat(web/model-admin): 后端 C0-C3（PATCH 启停、模型级 CRUD、live 默认、discover） |
| 40 | `.worktrees/lfl-child-subagent_ed13711c0655` | 1 | 1 | feat(wecom): 企微智能机器人双向对话桥 M0-1..M0-7 |
| 41 | `.worktrees/main-response-latency-20261023` | 1 | 15 | fix(webui): 排队插话撤回竞态 + ChatQueue 文案回字典（r5）——deferredWithdrawals 条件删除/合 |
| 42 | `.worktrees/p1a-release` | 1 | 0 | docs(write-scope): gen 345 发布范围与依据——候选 d94b6ce39 审查 REVISE 处置 + 改以 mai |
| 43 | `.worktrees/p2-escalation-argv-20261025` | 1 | 0 | fix(safety): argv 提权令牌按规范命令文本匹配，解除已批准命令的 fail-closed 死锁 |
| 44 | `.worktrees/p2-keyframe-unbind-20261025` | 1 | 0 | fix(realtime): keyframe 绑定在 sink 失败时回滚，解除视觉轮次死锁 |
| 45 | `.worktrees/p2-transport-close-20261025` | 1 | 0 | fix(realtime): 会话结束关闭 httpx 客户端，修复每会话连接池泄漏 |
| 46 | `.worktrees/realtime-loopback-auth-20261024` | 1 | 0 | fix: restore authenticated realtime voice session on loopback |
| 47 | `.worktrees/web-interaction-r4-20261026` | 1 | 18 | fix(webui): 排队插话撤回竞态 + ChatQueue 文案回字典（r5）——deferredWithdrawals 条件删除/合 |

## 可归档后删：无独立提交但有未提交改动（15 棵）

| # | 树 | 脏文件 |
|---|---|---|
| 1 | `lfl-service-gen-experience-20261025` | 27 |
| 2 | `.worktrees/cache-prefix-briefing-20261025` | 22 |
| 3 | `.releases/dd9dae4dbd3a3caa031a1803f8ae6b225358658a` | 18 |
| 4 | `.worktrees/m4-desktop-operate-20261031` | 18 |
| 5 | `.worktrees/web-interaction-20261026` | 18 |
| 6 | `.worktrees/web-interaction-main-20261026` | 18 |
| 7 | `.worktrees/p1a-verify` | 9 |
| 8 | `.worktrees/auth-migration-recovery-20261025` | 7 |
| 9 | `.worktrees/macos-v0637-integrate-20261026` | 6 |
| 10 | `.worktrees/redact-ci-fix` | 6 |
| 11 | `.worktrees/lfl-child-subagent_203bbbf1a08a` | 5 |
| 12 | `.worktrees/lfl-child-subagent_660185bfb17e` | 5 |
| 13 | `.releases/8c114428f3edbd44f3064dfc4412df574aebf127` | 2 |
| 14 | `.worktrees/fix-m3-followup-20261026` | 1 |
| 15 | `.worktrees/macos-v0637-tag-release-20261027` | 1 |

## `.releases`：第 2 步迁移已完成（2026-11-05），189 棵 / 约 17G 待统一清理

- 全部干净；188 个提交可从 refs 到达。**2 个不可达提交已建 ref**：
  `refs/archive/releases-salvage/wecom-m0-design-bae3c4a5` → `bae3c4a50`，
  `refs/archive/releases-salvage/wecom-direct-endpoint-f123e2e6` → `f123e2e69`。
- **阻塞点已解除**：krate 原从 `.releases/*/methods/` 兜底读 10 条种子方法。
  `tools/krate/krate_index.py::method_md_paths` 与 `tools/krate/krate_score.py::load_method`
  改为读 tracked 种子目录 `methods/`（顺序 `data/methods` → `methods`，与 runtime MethodStore 一致）。
  - 等价核验：迁移前后 krate 解析方法卡均 **1857 张、ref 名集合逐字节相同**；10 条种子卡全部来自 `methods/`，索引内无任何 `.releases` 路径。
  - 顺带修正：`method-root-cause`、`method-self-distill` 由 release 旧副本（2026-10-16，无 aliases）切回 tracked 副本（2026-10-23，含 aliases），name/description 未变。
  - 回归测试：`tests/unit/test_krate_seed_resolution.py`（3 例，含"只在 .releases 里的卡不可见"）。
- **清理前必须保留（live 引用）**：
  - `.releases/c390e67b12d842a5fc942a12407ab4b2f2a2a384` — web / feishu / learning 现役 code_root（generation 391）。
  - `.releases/0cb12757819540cf1a06e71b2df7311e64cc996f` — wecom 现役头（`live_git_head_mismatch`，待 restart 收敛到 c390e67b）。
- 剩余可清：187 棵已注册 worktree（逐棵 `git worktree remove --force`）→ `git worktree prune` → 删非注册残留目录。

## 两处未注册残留目录

- `.releases/0cd9c5248b00bea07e8bbdaf839da5a5d7b79d84.orig`（非 worktree，整份拷贝）
- `.releases/cb9c96daa9...`（worktree 注册已丢失，目录仍在）

## 已执行：47 棵删除（2026-11-05 17:0x，用户裁决「按建议执行」）

- 方式：逐棵 `git worktree remove --force`（47/47 成功）→ `git worktree prune`。分支未删（仅删检出）。
- 无损凭据（删除前建立，已实测可恢复）：
  - 47 个 HEAD 各建 ref：`refs/archive/triage-20261105/01-<sha>` … `47-<sha>`。
  - 10 棵脏树（`lfl-integration`、`evo-e0bff8ee-p2-int-20261025`、3×`lfl-child-subagent_*`、`kstore`、`main-response-latency-20261023`、`web-interaction-r4-20261026` 等）的 `git diff HEAD --binary` + `??` 文件 + status 存于 `.backup/worktree-archive-20261105/triage47/<名>/`（872K；`.tmp-rebase-work/` 171M 整份拷贝只登记名单、未存内容）。
  - 恢复示例（已实测）：`git worktree add --detach /tmp/restore refs/archive/triage-20261105/01-5747b28e`。
- 计数变化：注册 worktree 222 → 175（`.releases` 189 → 161，`.worktrees` 31 → 12）；`du -sh`：`.releases` 17G → 14G，`.worktrees` 4.9G → 2.3G。
- 未触碰：`.releases/c390e67b…`（web/feishu/learning 现役 code_root）与 `.releases/0cb12757…`（wecom 现役头）；4 个服务 alive 与 pid 删除前后一致。
- 回归：`tests/unit/test_krate_seed_resolution.py` 3 passed。
- 仍未做：161 棵 `.releases`（第 3 步，前置 wecom restart 收敛）、15 棵「可归档后删」脏树、2 处非注册残留目录、名称待核的未注册 `.worktrees` 目录。

## 已执行：15 棵脏树归档后删除（2026-11-05 17:0x，用户裁决「接着做 15 棵脏树的归档删除」）

- 对象：§「可归档后删」15 棵。删除前逐棵复核：15/15 存在、15/15 已注册、`git rev-list --count main..HEAD` 全为 0（文档「无独立提交」成立）、脏条目数 27/22/18/18/18/18/9/7/6/6/5/5/2/1/1 与文档一致。
- 无损凭据（删除前建立，已实测可恢复）：
  - 15 个 HEAD 各建 ref：`refs/archive/triage-20261105/dirty15/01-26530f9f` … `15-8c8bb997`（11、12 同指 `f5fec37c`，内容分别归档）。
  - 工作区状态存于 `.backup/worktree-archive-20261105/dirty15/<NN>-<名>/`（14M）：`status.txt`、`meta.json`、`diff.patch`（`git diff HEAD --binary`，合计 1.55MB）、`untracked/` + `untracked-manifest.json`（611 个文件 / 6.9MB，含 `dist/` 5.7MB、`webui/.tmpvitest/` 1.5MB）、`ignored-list.txt`（忽略项仅记名单：`.venv`、`node_modules`、`__pycache__` 等未归档）。
  - 归档完整性自检：15/15 通过——未跟踪文件逐个 sha256 与源一致、`diff.patch` 与源 `git diff HEAD --binary` 逐字节相同。
  - 恢复演练（删除前 4 棵：01 大 diff、13 小 diff、14 纯未跟踪 597 文件、15 纯未跟踪 `dist/`）：`git apply --binary` 全部成功，恢复后 `git status` 条目数 = 归档条目数（27/2/1/1）。删除后再演练 #13：`APPLY_OK`、2 条目。
  - 恢复示例：`git worktree add --detach <临时目录> refs/archive/triage-20261105/dirty15/13-8c114428` → `git apply --binary .backup/worktree-archive-20261105/dirty15/13-*/diff.patch`。
- 删除：逐棵 `git worktree remove --force` → `REMOVED=15 FAIL=0` → `prune`。含 repo 外同行目录 仓库同级目录 `lfl-service-gen-experience-20261025`。
- 计数变化：注册 worktree 175 → 160；`du -sh`：`.worktrees` 2.3G → 498M，`.releases` 14G（两次删除量小、未跨整 G 阈值）；`refs/heads` 90 个、涉及 9 个分支全部仍在（只删检出）。
- 未触碰：`c390e67b…`（web/feishu/learning code_root，generation 391）、`0cb12757…`（wecom 现役头）。4 个服务 alive，pid 删除前后一致：web 76872 / feishu 76956 / learning 77206 / wecom 31632；wecom 仍 `restart_required=true`（删除前既有状态）。
- 主树另有并发 WIP（非本轮产生，mtime 15:44–15:54）：`docs/design/DESIGN-20261105-main-lane-parallel-delivery-v1.md`、`src/llm_loop/introspection/{merge_queue,tools_merge_queue}.py`、`src/llm_loop/tools/builtin/execute_command.py`——本轮未触碰、未提交。
- 仍未做：160 棵 `.releases`（第 3 步，前置 wecom restart 收敛）、2 处非注册残留目录、5 个未注册 `.worktrees` 目录。

## 已执行：`.releases` 清理（2026-11-05 17:1x，第 3 步；用户裁决「先动 wecom 的 restart 把第 3 步前置解开」）

- 前置动作：wecom 单独 restart（action `svc-1ff6383330754181a0398210c64ba6d9`，expected_generation=391）→ 终态 succeeded：pid 31632 → 44098，live head `0cb12757…` → `c390e67b…`，`restart_required=false`。四服务同代 391、`matches_desired_generation=true`。
- 删除前逐棵复核（159 棵已注册 `.releases` worktree，清单 `.backup/triage-step3/preflight.tsv`）：
  - `status --porcelain` 全部 0 条（无脏文件）；
  - 159/159 的 HEAD 均被 ref 包含（`git for-each-ref --contains` 计数 ≥1）；
  - 目录名与 HEAD 逐一相符；`git worktree list` 中 0 个 locked；无进程 cmdline/cwd 指向 `.releases/`（四服务 cwd 均为 runtime root）。
- **实际保留 3 棵（偏离本节原计划，因发现回滚依赖）**：现役 `c390e67b…`（code_root）+ 最近两条 known-good `356cbf87b…`（15:02 action=all）、`ab2e3ddf3139…`（14:00 action=all）。
  - 依据：`service_control._find_known_good_release()` 倒扫 `data/restart-receipt.log`，取第一条 `rc==0 && authority==service_control` 且**要求 `.releases/<sha>` 目录仍在（含 `scripts/restart_mirror.sh`）**，否则返回 None = 不回滚、不猜测。若 159 棵全删只剩现役，则该代 restart 失败时无回滚目标。
  - 复检：清理后 `known_good.py` 仍命中 `356cbf87b`，回滚面未失效。
- 删除：逐棵 `git worktree remove --force` → `REMOVED=156 FAIL=0 SKIP=3` → `git worktree prune`。
- 可恢复性（实测，非推断）：`.releases/<sha>` 是纯衍生工件（`_materialize_release_checkout` 幂等重建，见 `service_control.py`）。删除前 2 次、删除后 1 次 `git worktree add --detach` 实测：`04ff8664d`、`943232933`、`356cbf87b` 全部重建成功，tracked 文件 8228 个、含 `scripts/restart_mirror.sh`，重建后 `status` 0 条；探针树均 `remove --force` + `prune` 清掉。
- 计数变化：`.releases` 14G → **648M**（161 项 → 5 项 = 3 棵保留 + 2 处非注册残留）；注册 worktree 160 → **4**（main + 3 棵 release）；`refs/heads` 仍 90、`refs/archive` 104（其中 `refs/archive/triage-20261105` 62），分支一个未删。
- 删除前后四服务 alive 且 head 均为 `c390e67b12d8`：web 76872 / feishu 76956 / learning 77206 / wecom 44098。
- 脚本与日志：`.backup/triage-step3/{preflight.sh,preflight.tsv,remove_releases.sh,remove.log,known_good.py,show_manifests.py}`。
- 残留与未注册目录：第 3 步时仍未处理，已在下一节按用户裁决清理完毕。

## 已执行：残留与未注册目录清理（2026-11-05 17:16，用户裁决「删」）

- 范围（7 项，`REMOVED=7 FAIL=0`）：`.releases/0cd9c524….orig`、`.releases/cb9c96daa9…`（94M/96M）、`.worktrees/review-origin-a72df001.git`（479M bare）、`.worktrees/statebraid-{merged,shadow-a,shadow-b}`（各 6.2M）、`.worktrees/main-response-latency-20261023\.cache\dsh-capability-index`（4K，名字含字面反斜杠）。
- 删除前事实核查（未沿用前文结论，逐项重取）：
  - 两个 `.releases` 残留：HEAD 分别位于 101 / 83 个 ref 的祖先链上，`status --porcelain` 均 0 条，`.git/worktrees` 无对应 admin 目录 → 纯衍生工件，可重建。
  - `review-origin-a72df001.git`：`is-bare=true`，123 个 ref 全部在主仓库可达（missing=0）；但 3351 个 dangling 对象（含 `WIP on main` commit `510108132`，2026-09-22）仅存于该 bare 库 → 先落盘清单后删。
  - `statebraid-*` 三个：`.git` 是目录 = 独立克隆（remote 指向 `research/StateBraid`），**不是本仓库 linked worktree**；且含与上游不同的未提交改动（`cache/policy.py` 69 行、`tests/test_cache_policy.py` 133 行，新增 `cache/canary.py`、`tests/test_cache_canary.py`）→ 先归档后删。
- 无损凭据（删除前建立）：`.backup/triage-step3/stray-20261105-171610/`
  - `statebraid-{merged,shadow-a,shadow-b}.{tracked.diff,untracked.tgz,HEAD,status}`：diff 302 / 261 / 41 行；tgz 含 `canary.py` + `test_cache_canary.py`（shadow-a 无未跟踪文件，空包含义为无内容，符合核查结论）。
  - `review-origin.refs`（123 行）、`review-origin.orphans`（3351 行 sha 清单）、`decisions.jsonl`（3 条运行期决策记录）。
  - 恢复方式：先 `git worktree add --detach <tmp> <该树 HEAD>`，再 `git apply` 对应 `tracked.diff` + `tar -xzf` 未跟踪包。review-origin 的 dangling 对象无法由清单还原二进制，清单仅作审计痕迹（该目录为 bare 镜像，123 个 ref 已确认主仓库全覆盖）。
- 结果：`.releases` 648M → **457M**（剩 3 棵保留 + `.bak-dd9dae4db`）；`.worktrees` 498M → **0B**（空目录保留，程序按需重建）；注册 worktree 仍 **4**（main + 3 棵 release）。
- 未触碰：`.releases/.bak-dd9dae4db`（96M，备份命名、不在本次「2 处 + 5 个」授权清单内，待裁定）；主树 18 个并发 WIP（他人会话）。
- 四服务删除前后 alive，head 均 `c390e67b12d8`、generation 391、`restart_required=false`：web 76872 / feishu 76956 / learning 77206 / wecom 44098。
- 脚本：`.backup/triage-step3/clean-stray.sh`（默认 dry-run，`DRY_RUN=0` 实删）。
