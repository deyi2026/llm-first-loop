from __future__ import annotations
import hashlib,json,pathlib,random,re
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[2]
METHODS=ROOT/'data'/'methods'
SEED=20261006
FORBIDDEN=[r'没有',r'不存在',r'不需要',r'不是',r'尚未',r'并非',r'只需要',r'只问',r'当前唯一目标',r'只是',r'不涉及']

def sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def card(mid:str)->dict:
 p=METHODS/mid/'METHOD.md'; raw=p.read_text(encoding='utf-8'); m=re.match(r'^---\n(.*?)\n---\n(.*)$',raw,re.S); assert m,mid
 meta,body=m.groups()
 def s(k):
  x=re.search(rf'^{k}:\s*(.+)$',meta,re.M); return x.group(1).strip() if x else ''
 return {'method_id':mid,'name':s('name'),'description':s('description'),'body':body.strip(),'sha256':sha(raw.encode())}
def card_text(c):return f"name: {c['name']}\nmethod_id: {c['method_id']}\ndescription: {c['description']}\n\n{c['body']}"

B=[
# family 1: same object, different action
('same_object_different_action','allowlist-names-from-authoritative-definition-not-summary-28a550ac5cac','zero-hit-from-indexed-search-is-not-code-absence-proof-fa972dda9005','一份审查摘要声称代码中存在标识符 A/B；索引搜索返回零命中。任务是核验这些标识符是否真实存在并定位定义位置，输出核验结论。','标识符/权威定义/摘要','任务核验标识符存在性；subject Method 面向写入逐字枚举工件前的名集提取。'),
('same_object_different_action','bounded-chunk-write-verify-for-long-file-artifacts-45c00c2ebf00','bound-verification-output-to-survive-truncation-5879c1e4cca7','pytest 输出包含大量 warning，工具窗口经常截掉末尾 summary 与退出码。任务是把验证命令塑造成短输出，保留最终 summary 和 exit code。','截断/验证/输出','任务压缩验证命令输出；subject Method 面向长文件写入传输的分块与落盘核验。'),
('same_object_different_action','batch-complete-required-fields-on-parameter-rejection-71b35b88bd44','bare-id-state-reconcile-before-transition-retry-588019de930e','此前 complete 动作已经发出，当前有 action ID 与状态存储入口。任务是读取该 ID 的最新记录并决定后续状态迁移。','complete/action ID/状态迁移','任务先对账已发起动作的最新状态；subject Method 面向参数缺失型拒绝后的字段补全重试。'),
('same_object_different_action','anchor-evidence-to-instance-lifecycle-window-fffe781df7d0','anchor-process-verification-on-deployment-identity-1a2a8ee84ad1','服务完成重启，部署记录给出 runtime_root 与 git_head。任务是检查当前进程列表中的目标实例是否来自该部署身份，并输出一致性清单。','进程/重启/部署身份','任务核对当前进程的部署身份；subject Method 面向跨进程生命周期证据切窗与当前实例复现。'),
('same_object_different_action','anchor-on-unique-identifier-to-find-mechanism-ae14900fecb5','async-action-terminal-ledger-first-7f9a435b6e99','此前异步 restart 已受理，action ID 和专属台账路径都已知。任务是读取终态并核对反馈通道的呈现状态与动作结果。','action ID/台账/restart','任务沿已知 action 读取终态和反馈；subject Method 面向借唯一标识定位未知 producer/consumer 机制。'),
('same_object_different_action','binding-identity-gate-before-destructive-ops-9e1d9ef8f671','binding-verify-config-first-probe-86ba90942add','浏览器重启后，.env 给出 CDP 端口和 TARGET_ID。任务是按这些值探测端点并确认目标绑定一致。','数字标识/CDP/目标归属','任务验证连接绑定一致性；subject Method 面向破坏性操作前确认数字标识的实体类别与归属。'),
# family 2: same evidence, different claim
('same_evidence_different_claim','artifact-symbol-lineage-before-mechanism-reading-e22289ec79cf','audit-report-by-resolving-cited-pointers-4cbbd66a7689','分析报告中的事实声明都带 commit/hash/URL/内部 ID。任务是逐个解析这些指针，以权威来源给出证实、证伪或证据缺口。','报告/工件/指针证据','任务裁定报告声明真伪；subject Method 面向共享数据工件的写入者符号血缘归因。'),
('same_evidence_different_claim','anchor-first-claim-audit-81071f5c9dc1','authoritative-record-first-when-preview-truncated-0155675ee421','用户给出唯一 EVO ID，records 索引返回截断预览。任务是按 ID 从持久台账取回完整记录并依其规格继续执行。','EVO记录/索引预览/权威台账','任务恢复具名规格全文；subject Method 面向报告事实声明的持久状态锚点优先审计。'),
('same_evidence_different_claim','audit-closure-via-transition-event-receipts-not-artifact-grep-da92ba3b84c6','audit-duplicates-via-unfiltered-timeline-and-controlflow-boundary-340f7604d311','会话出现重复工具调用，期间经历 wake、compact、handoff。任务是拉取完整事件流并定位重复从哪个控制流边界开始。','事件流/控制流/工具调用','任务解释重复动作的控制流来源；subject Method 面向生命周期阶段转移与闭环回执证明。'),
('same_evidence_different_claim','anchor-verification-over-narrative-recovery-73fa76a07438','answer-terse-ref-from-authoritative-goal-record-bound-recovery-f5a3ce3d72c2','用户说把前两个收口项完成；active Goal 回执恰好列出两个已完成条目和时间戳。任务是把这两个条目映射到用户回指并直接答复。','Goal回执/历史上下文/完成证据','任务解析当前回指；subject Method 面向核验旧叙述声称是否已经落实。'),
('same_evidence_different_claim','bare-citation-anchor-not-path-guess-c0caae461a97','authoritative-artifact-first-then-live-contract-probe-6867db304150','一条回执提供证据文件的完整绝对路径 `/tmp/run42/ATTRIBUTION.md` 与 sha256。任务是读取该路径、校验 sha256，并提取结论。','证据工件/路径/引用','任务按已知绝对路径读取工件；subject Method 面向裸文件名引用下的路径定位。'),
('same_evidence_different_claim','audit-report-by-resolving-cited-pointers-4cbbd66a7689','audit-duplicates-via-unfiltered-timeline-and-controlflow-boundary-340f7604d311','给定 session ID 和完整事件流，任务是定位两次相同工具调用之间的 wake/compact/handoff 边界并解释重复来源。','会话证据/事件ID/审计','任务分析单会话控制流重复；subject Method 面向带可解析指针的分析报告逐声明核验。'),
# family 3: same workflow, different phase
('same_workflow_different_phase','attribute-suite-failures-via-touched-set-and-clean-head-worktree-8d92c40cb6dc','complete-failure-inventory-before-root-cause-ce230cde7fa6','CI 原始日志可完整读取，任务是从 short summary 与 FAILED/ERROR 行建立完整失败清单和数量，作为后续诊断输入。','CI失败/测试日志/诊断','任务建立失败全集；subject Method 面向失败集合已知后的 touched-set 与 clean-HEAD 因果归因。'),
('same_workflow_different_phase','complete-failure-inventory-before-root-cause-ce230cde7fa6','attribute-suite-failures-via-touched-set-and-clean-head-worktree-8d92c40cb6dc','失败清单已经固定，定向测试也有结果。任务是把失败主题与本次 touched set 求交，并用 clean HEAD worktree 对照判断因果归属。','CI失败/测试清单/根因诊断','任务已进入因果归因阶段；subject Method 面向先钉死完整失败清单。'),
('same_workflow_different_phase','authority-contract-before-managed-mutation-62e4436f179e','binding-drift-preflight-before-gated-service-mutation-e6f2166d36f7','部署记录的 git_head 与当前 HEAD 出现差异，并行会话还留下 dirty 增量。任务是完成 binding drift preflight，判断受管变更是否会被 fence 接纳。','受管变更/部署身份/前置门','任务判定 binding drift 与可接纳性；subject Method 面向先确定动作权限归属。'),
('same_workflow_different_phase','async-wait-on-pipeline-conclusion-not-artifact-03a2fa7c25cb','bounded-probe-before-blocking-retry-e3e7b0a91b65','上轮 git fetch 挂起；当前任务是对 remote host 做 8 秒网络探针，分类传输层状态并决定下一次 fetch 时机。','等待/重试/远端状态','任务对阻塞网络重试做有界故障分类；subject Method 面向异步 pipeline 的终态结论等待。'),
('same_workflow_different_phase','assertions-as-spec-first-for-behavior-edits-c1f836aa31cd','bulk-edit-from-displayed-literal-anchor-free-per-surface-verify-95849638b2f5','同一个版本号需要同步到 pyproject、源码常量和 README；预检 grep 已列出三处完整字面行。任务是完成替换并逐表面核对新值。','多文件编辑/验证/版本面','任务执行多表面字面量迁移；subject Method 面向行为或指标契约变更时以断言作为规格。'),
('same_workflow_different_phase','attach-feasibility-gate-then-authoritative-config-42e640eda0c3','binding-verify-config-first-probe-86ba90942add','浏览器重启后，.env 中记录了当前 CDP URL 与 TARGET_ID。任务是读取这些值并验证端点和目标仍保持同一绑定。','浏览器/CDP/配置探针','任务按权威配置做重绑一致性验证；subject Method 面向接入失败场景先判断 attach 可行性。'),
# family 4: same infrastructure, different decision
('same_infra_different_decision','anchor-on-self-report-then-probe-gaps-003c0af478b6','binary-intervention-sufficiency-gate-7631f80e335c','用户报告外部访问异常并询问是否重启；监督者显示进程 running，公网端到端请求返回应用级 HTTP 303。任务是据此裁决重启动作。','服务健康/状态/重启决策','任务用最小事实对裁决二元干预；subject Method 面向 authoritative self-report 存在时以其状态字段为主锚。'),
('same_infra_different_decision','anchor-process-verification-on-deployment-identity-1a2a8ee84ad1','anchor-evidence-to-instance-lifecycle-window-fffe781df7d0','同一运行日志跨过数次服务重启，当前实例的 pid 与启动时刻已知。任务是切出当前实例证据窗口并复现连接缓存异常。','进程/重启/实例身份','任务用生命周期身份切证据窗口并复现异常；subject Method 面向重启后核对进程是否落在目标部署身份。'),
('same_infra_different_decision','binding-drift-preflight-before-gated-service-mutation-e6f2166d36f7','authority-contract-before-managed-mutation-62e4436f179e','受管系统准备执行 publish/restart，当前工具 schema 暴露 status/restart，代码注释描述 desired deployment 的发布责任。任务是先确定各动作的权限归属。','受管服务/变更门/发布重启','任务判动作 authority contract；subject Method 面向已知权限契约下的代码树与部署绑定漂移。'),
('same_infra_different_decision','bounded-probe-before-blocking-retry-e3e7b0a91b65','async-wait-on-pipeline-conclusion-not-artifact-03a2fa7c25cb','CI workflow 正在后台运行，release artifact 由成功终态产生。任务是查询 workflow conclusion，并依据终态决定后续处理。','等待/异步状态/终态','任务等待异步 pipeline 的结论；subject Method 面向阻塞式命令重试前的本地有界探针。'),
('same_infra_different_decision','binding-verify-config-first-probe-86ba90942add','binding-identity-gate-before-destructive-ops-9e1d9ef8f671','准备对一个数字标识执行进程终止操作。任务是先判断该数字代表 PID、端口还是目标 ID，并核对它归属的进程实体。','数字标识/进程/绑定','任务是破坏性操作前的实体身份门；subject Method 面向重启后按配置值验证外部连接绑定。'),
('same_infra_different_decision','binary-intervention-sufficiency-gate-7631f80e335c','anchor-on-self-report-then-probe-gaps-003c0af478b6','用户询问系统当前健康状态，权威 status 接口直接返回 healthy 与状态摘要。任务是据此判断是否需要展开更宽的诊断。','服务健康/状态/诊断','任务以权威 self-report 回答健康问题；subject Method 面向用户提出重启/回滚等二元干预请求时的最小事实裁决。'),
]

APPLY=[
('allowlist-names-from-authoritative-definition-not-summary-28a550ac5cac','契约测试的允许字段清单要与当前 schema 对齐；现有审查摘要也列了一组字段名。任务是从 schema 与前端类型机械提取真实名集、对比摘要，再写入允许集。'),
('bounded-chunk-write-verify-for-long-file-artifacts-45c00c2ebf00','需要用 shell heredoc 生成约 260 行报告，历史传输曾在命令成功时留下短文件。任务是分块写入并逐块核对行数与最终 sha256。'),
('artifact-symbol-lineage-before-mechanism-reading-e22289ec79cf','运行时指标异常来自共享审计目录里的 ledger 行。任务是先追出该工件由哪个符号、提交与 writer 生成，再判断对应机制是否影响指标。'),
('audit-closure-via-transition-event-receipts-not-artifact-grep-da92ba3b84c6','需要证明一条 Method 生命周期是否真正从 save 经过 use 到 activate 完成闭环。任务是读取阶段转移事件与回执，核对每个 transition 的终态。'),
('attribute-suite-failures-via-touched-set-and-clean-head-worktree-8d92c40cb6dc','本轮改动的定向测试全绿，更大测试集出现已知失败清单。任务是用 touched set 与 clean HEAD 对照判定这些失败是否由本轮改动引入。'),
('authority-contract-before-managed-mutation-62e4436f179e','受管 desired-state 系统准备执行 publish/restart，当前工具面与源码对发布权限的归属需要先核实。任务是确定动作 authority contract 后再做变更。'),
('anchor-on-self-report-then-probe-gaps-003c0af478b6','用户询问服务是否健康，系统提供权威 status 接口并直接返回 healthy 与状态字段。任务是先用该 self-report 回答，再决定诊断缺口。'),
('anchor-process-verification-on-deployment-identity-1a2a8ee84ad1','服务重启回执给出目标 generation、runtime_root 与 git_head。任务是从进程列表核对所有目标实例是否运行在这组部署身份上。'),
]

old_texts=set()
for p in [ROOT/'evals/method_binding_efficacy_v1/pool.json',ROOT/'evals/method_binding_efficacy_v2/goldset_candidates.json']:
 if p.exists():
  j=json.loads(p.read_text())
  cases=j.get('cases',{})
  for c in cases.values(): old_texts.add(c.get('trigger') or c.get('task') or '')
old_hashes={sha(t.encode()) for t in old_texts if t}
rows=[]
for i,(fam,subject,source,task,shared,purpose) in enumerate(B,1):
 c=card(subject); hits=[pat for pat in FORBIDDEN if re.search(pat,task)]
 assert not hits,(i,hits,task)
 assert sha(task.encode()) not in old_hashes,(i,'old task reuse')
 rows.append({'case_id':f'v3d-B{i:02d}','kind':'challenge','family':fam,'intended':'SKIP','subject_method_id':subject,'source_method_id':source,'task':task,'shared_surface':shared,'purpose_divergence':purpose,'card':card_text(c),'card_sha256':c['sha256'],'anti_leak_hits':hits})
for i,(subject,task) in enumerate(APPLY,1):
 c=card(subject); assert sha(task.encode()) not in old_hashes
 rows.append({'case_id':f'v3d-A{i:02d}','kind':'apply_control','family':'apply_control','intended':'APPLY','subject_method_id':subject,'source_method_id':subject,'task':task,'shared_surface':'self','purpose_divergence':'self-applicable control','card':card_text(c),'card_sha256':c['sha256'],'anti_leak_hits':[]})
assert len(rows)==32 and len({r['task'] for r in rows})==32
assert {f:sum(r['family']==f for r in rows) for f in ['same_object_different_action','same_evidence_different_claim','same_workflow_different_phase','same_infra_different_decision']}=={f:6 for f in ['same_object_different_action','same_evidence_different_claim','same_workflow_different_phase','same_infra_different_decision']}
for r in rows:r['opaque_id']=sha(('v3-dev|'+r['case_id']).encode())[:12]
order=list(range(len(rows))); random.Random(SEED).shuffle(order); presented=[rows[i] for i in order]
out={'schema':'subject-binding-v3-dev-pool/v1','seed':SEED,'source_contract_sha256':sha((ROOT/'evals/method_binding_efficacy_v2/posthoc_opportunity_v1/V3-CALIBRATION-CONTRACT.md').read_bytes()),'rows':{r['case_id']:r for r in rows}}
(HERE/'dev_candidates.json').write_text(json.dumps(out,ensure_ascii=False,indent=1)+'\n')
sealed={'schema':'subject-binding-v3-dev-sealed/v1','present_order':[r['opaque_id'] for r in presented],'cases':{r['opaque_id']:{k:r[k] for k in ('case_id','kind','family','intended','subject_method_id','source_method_id','purpose_divergence')} for r in rows}}
(HERE/'dev_sealed.json').write_text(json.dumps(sealed,ensure_ascii=False,indent=1)+'\n')
lines=['# Subject-Binding v3 development blind label sheet','', 'Judge whether the Method card is applicable to the task. Return APPLY or SKIP and one concise Chinese reason comparing task purpose with Method purpose.','']
for n,r in enumerate(presented,1): lines += [f'## {n}. {r["opaque_id"]}','','TASK','',r['task'],'','METHOD CARD','',r['card'],'']
(HERE/'BLIND-SHEET.md').write_text('\n'.join(lines))
for b in range(4):
 chunk=presented[b*8:(b+1)*8]; q=[f'# Blind batch {b+1}/4','', 'Return one JSON object per case with opaque_id, verdict APPLY|SKIP, and one-line Chinese reason comparing task purpose with Method purpose.','']
 for n,r in enumerate(chunk,1):q += [f'## {n}. {r["opaque_id"]}','','TASK','',r['task'],'','METHOD CARD','',r['card'],'']
 (HERE/f'blind_batch_{b+1}.md').write_text('\n'.join(q))
print('rows',len(rows),'challenge',sum(r['kind']=='challenge' for r in rows),'apply',sum(r['kind']=='apply_control' for r in rows))
print('anti_leak_challenge',sum(bool(r['anti_leak_hits']) for r in rows if r['kind']=='challenge'))
print('fresh_tasks',sum(sha(r['task'].encode()) not in old_hashes for r in rows),'/',len(rows))
print('sheet_sha256',sha((HERE/'BLIND-SHEET.md').read_bytes()))
