from __future__ import annotations
import hashlib,json,pathlib,random,re
H=pathlib.Path(__file__).resolve().parent; ROOT=H.parents[2]; METHODS=ROOT/'data'/'methods'; SEED=20261006
FORB=[r'没有',r'不存在',r'不需要',r'不是',r'尚未',r'并非',r'不涉及',r'只需要',r'只问',r'当前唯一目标']
def sha(b):return hashlib.sha256(b).hexdigest()
def card(mid):
 p=METHODS/mid/'METHOD.md'; raw=p.read_text(); m=re.match(r'^---\n(.*?)\n---\n(.*)$',raw,re.S); assert m,mid; meta,body=m.groups()
 def s(k):
  z=re.search(rf'^{k}:\s*(.+)$',meta,re.M); return z.group(1).strip() if z else ''
 d={'method_id':mid,'name':s('name'),'description':s('description'),'body':body.strip(),'sha256':sha(raw.encode())}; assert d['name'] and d['description']; return d
def card_text(c):return f"name: {c['name']}\nmethod_id: {c['method_id']}\ndescription: {c['description']}\n\n{c['body']}"
def desc(mid):return card(mid)['description']
CH=[
('same_object_different_action','failure-receipt-is-zero-info-not-absence-20ac7bad5b0a','falsify-error-receipt-on-identical-recurrence-verify-echoed-input-c0166d5a76ba','结构化工具回执把 artifact_missing 指向调用方提供的 code_root；按回执处方执行后同一错误逐字复现。任务是对照权威 status 与路径存在性，确定规范 root 的真实来源并纠正输入。','失败回执/路径/权威状态','任务校验回显输入与真实 root；subject Method 用失败/超时检索回执区分“零命中”与“零信息”。'),
('same_object_different_action','failing-test-red-triage-by-failure-signature-86ac002c4e46','false-red-guard-delegate-to-truth-source-e38f5294fa10','仓库守卫脚本报红，而同一契约的权威单元测试通过；失败项对应守卫脚本内的旧路径常量。任务是把复制的契约检查改成委托权威测试，并用负向探针验证委托有效。','测试失败/契约/守卫','任务修复假红守卫的重复真相源；subject Method 面向多失败测试的签名分诊与根因分类。'),
('same_object_different_action','failed-action-keyed-ledger-lookup-then-prescribed-remediation-efed0f93c3f4','durable-job-defer-terminal-check-2a5ca0503c58','后台部署任务已受理并返回 action_id，当前状态为 durable/running。任务是安排一次延迟检查，到点读取该 action 的终态并据结果继续。','action_id/后台任务/终态','任务处理仍在运行的 durable job；subject Method 面向已经卡住或失败的 action 读取失败台账并执行补救。'),
('same_object_different_action','deploy-acceptance-follow-change-identity-b334d83e67f1','derive-delivery-gates-from-repo-history-preverify-locally-0f4fbb2a1558','本地分支准备同步到受保护共享仓库，git log 显示历史提交总伴随 submission manifest 与 PR merge。任务是推导交付契约、按路径分组生成清单并在推送前本地预验。','commit/变更路径/交付','任务准备提交交付门禁；subject Method 面向发布完成后的 change identity 验收。'),
('same_object_different_action','derive-delivery-gates-from-repo-history-preverify-locally-0f4fbb2a1558','deploy-acceptance-follow-change-identity-b334d83e67f1','服务发布回执给出 generation 与 git_head，验收项点名会话隔离和 SSE 行为。任务是沿该 commit 的改动文件选择针对性测试，并完成进程、入口与新启动日志验证。','git_head/提交/部署','任务执行发布后的功能和运维验收；subject Method 面向提交进入受保护远端前的 PR/manifest 交付契约。'),
('same_object_different_action','deterministic-404-is-an-answer-pivot-to-canonical-candidate-daaa7d2b6d35','definitive-failure-swap-source-not-restart-discovery-5abed48afb10','研究任务中的一个来源连续返回 403，UA 轮换和备用抓取后端也得到相同结果；首轮候选列表还有多个未读同主题来源。任务是换到下一未读来源继续满足信息需求。','网页来源/失败回执/候选池','任务处理访问策略封锁并替换来源；subject Method 面向具名资源的确定性 404 存在性反证与规范候选转向。'),
('same_evidence_different_claim','drilldown-via-named-source-kind-before-keyword-search-7cee909454b4','dominant-reason-literal-to-emission-site-94d0631e6859','后台组件的 journal 连续记录 requeue reason；任务是统计 reason 分布，锁定占绝对多数的字面量，再到实际运行代码树追踪该 reason 的发射点。','结构化日志/reason/代码','任务用 reason 分布裁定因果并追发射点；subject Method 面向报告已点名 record kind 时直接按 kind 下钻指标证据。'),
('same_evidence_different_claim','dup-forensics-volatile-field-identity-plus-copy-lineage-2e19786207b7','falsify-selection-premise-via-origin-target-ledger-570c187396ab','append-only action 台账可按 origin 与 target 统计。任务是核对被指责的 publish 机制是否实际派发过动作，以及 target 分布是否支持“漏掉某服务”的前提。','append-only台账/事件字段/机制归因','任务用 origin×target tally 证伪选择前提；subject Method 面向跨实体重复记录的易变字段一致性与复制谱系。'),
('same_evidence_different_claim','denial-signature-records-first-b749e7b81591','falsify-mechanism-attribution-via-remedy-reproduction-23940a181dc9','一份 lesson 声称某隐藏状态导致工具失败，并给出清除该状态的修复办法。任务是原样复现，再只叠加该修复项，结合独立工具对照判断这条机制归因是否成立。','失败证据/记录/机制归因','任务复现实验检验 lesson 的因果归因；subject Method 面向环境级 EPERM 拒绝签名与用户的近期变更归因。'),
('same_evidence_different_claim','falsify-mechanism-attribution-via-remedy-reproduction-23940a181dc9','denial-signature-records-first-b749e7b81591','多个不同命令都在账户自有路径的 lock open-for-write 上返回 EPERM，用户认为近期重启禁用了工具。任务是用被指责子系统的状态回执和既有经验记录，裁定该因果说法并确定人机分工。','失败回执/状态/经验记录','任务裁定环境写拒绝与近期重启的因果关系；subject Method 面向带“根因+修复”机制断言的单变量复现实验。'),
('same_evidence_different_claim','external-update-merge-status-via-remote-setdiff-not-label-search-36ab77644027','derive-delivery-gates-from-repo-history-preverify-locally-0f4fbb2a1558','用户用一个平台俗称询问外部来源的更新是否已经并入当前运行版本。任务是枚举 remotes，比较 main 与各 remote/main 的提交集合，并结合进程 HEAD 给出生效结论。','git历史/remote/运行HEAD','任务判断外部更新是否已经合并生效；subject Method 面向从仓库历史推导未来提交的 PR/manifest 交付契约。'),
('same_evidence_different_claim','documented-availability-limits-and-logs-before-config-archaeology-ad25f7196c99','failure-receipt-is-zero-info-not-absence-20ac7bad5b0a','记录库查询返回 tool_timeout，而系统另有事件流与精确标识符检索入口。任务是把这次失败视为存在性零信息，改用窄查询和独立 provenance 通道确认决议是否保存。','失败回执/记录库/诊断','任务判断查询失败对“是否存在”的证据含义；subject Method 面向功能不可用时用官方限制、注册表与错误码区分服务端权限和本地配置。'),
('same_workflow_different_phase','failed-ci-gate-diagnose-from-local-gate-script-repro-04eed411f3de','failure-scoped-ci-log-triage-f602c22331b4','PR checks 已显示一个具名 gate FAILURE 并给出 run/job ID。任务是只读取该检查的失败步骤输出，提取 gate 自身的错误行与违规清单，确定下一跳诊断对象。','CI gate/失败日志/检查ID','任务处于失败输出定位阶段；subject Method 面向失败命令已点名本地 gate 脚本后，用相同 base/head 做本地复现与修复。'),
('same_workflow_different_phase','failure-scoped-ci-log-triage-f602c22331b4','failed-ci-gate-diagnose-from-local-gate-script-repro-04eed411f3de','失败步骤日志已经显示仓库内 gate 脚本及其 --base/--head 参数，错误指向 submission manifest 覆盖。任务是读取该脚本与样例，在本地用 CI 相同差分复现并迭代到 PASS。','CI gate/失败步骤/base-head','任务已经进入本地复现与修复阶段；subject Method 面向先从 named FAILURE 中收窄并取得失败输出。'),
('same_workflow_different_phase','diagnose-known-failing-tests-via-node-scoped-max-tb-rerun-25ece289a3f8','false-red-guard-delegate-to-truth-source-e38f5294fa10','守卫脚本的固定清单落后于权威契约测试，权威测试当前为绿。任务是删除复制的判定逻辑，改成 subprocess 委托权威测试并加入超时、runner 缺失和负向探针。','测试/守卫/契约','任务修复已判定的 false-red 设计；subject Method 面向精确失败节点已知后用单节点高 traceback 诊断断言根因。'),
('same_workflow_different_phase','explicit-redeclare-target-env-on-generation-switch-6e73ca09c81d','deploy-acceptance-follow-change-identity-b334d83e67f1','一次发布已经完成并返回 generation 与 git_head。任务是依据该变更身份检查受影响文件、运行针对性测试，并核验新进程、入口和启动后日志。','部署/世代/环境','任务处于部署后的验收阶段；subject Method 面向持久 shell 切换目标世代时在部署调用前重声明环境变量。'),
('same_workflow_different_phase','durable-job-defer-terminal-check-2a5ca0503c58','failed-action-keyed-ledger-lookup-then-prescribed-remediation-efed0f93c3f4','异步 restart action 已进入 failed 终态，action_id 可直接定位逐操作记录。任务是读取 failure detail、problem_kind、next_step，验证前置条件后执行规定补救序列。','异步action/终态/台账','任务处理已失败的 action 并补救；subject Method 面向 durable/running 任务把时间型未知延后到一次终态检查。'),
('same_workflow_different_phase','failing-daemon-own-log-first-fix-at-real-supervisor-297cab3af0ce','derive-endpoint-from-live-pid-before-probe-64db93a2fd0f','服务重启替换了进程，status 回执给出新的 live PID。任务是从该 PID 推导当前实际绑定端口，再对得到的端点执行一次健康探针。','常驻进程/重启/端点','任务处于重启后端点发现与探针阶段；subject Method 面向复发守护进程故障从进程日志定位缓存坏地址并修正 supervisor 配置。')]
AP=[
('deferred-action-failure-layer-scoped-lifecycle-trace-ae4184904e2b','定时唤醒到点后没有生成新 run；系统快照显示 pending=0、runtime healthy、执行槽被单一前台任务占用。任务是转向系统级调度生命周期事件，定位触发到 run 交接层并制定不依赖共享授权的兜底。','后台 job 已受理并保持 running，action_id 可查询，计划在预估完成时刻读取一次终态。'),
('derive-endpoint-from-live-pid-before-probe-64db93a2fd0f','服务重启后 status 给出新的 live PID，而先前记忆中的端口属于旧进程。任务是从新 PID 读取实际监听端点，再执行一次 canary 探针。','部署回执给出 git_head 与 generation，验收清单列出变更文件对应的针对性测试。'),
('fastfail-ci-gate-filtered-verdict-then-named-artifact-14e1acb2a084','PR checks 中某机械 gate 在数秒内失败。任务是读取该 gate 的失败步骤一行判定，沿判定点名的 artifact 路径读取 schema 与最近通过样例，再按相同 base/diff 语义本地复跑。','失败步骤已显示仓库 gate 脚本和 base/head 参数，准备完整本地复现。'),
('falsify-behavior-premise-before-inherited-change-6c6091650c9c','上轮提议以“机制只计算而不产生效果”为前提要求接入新闸门。任务是先检索 reason_code、BLOCKED 回执和判定函数调用点，验证该前提后再决定是否设计改动。','一份 lesson 给出机制根因与修复，需要做单变量复现实验验证归因。'),
('false-red-guard-delegate-to-truth-source-e38f5294fa10','守卫脚本因复制的旧路径清单报红，而权威契约测试通过。任务是把守卫改为调用权威测试并透传退出码，增加 runner 缺失、超时和负向探针验证。','多个失败测试节点已知，准备按节点重跑并读取详细 traceback。'),
('diff-normalization-parity-probe-before-wiring-13850e612a58','重构把原先内联 query.lower() 替换成共享 helper，diff 显示新 helper 保留了其他逻辑。任务是在接线前用大小写对照探针验证归一化语义等价，再决定是否继续重构。','CI gate 秒级失败并点名一个 artifact，需要先读取失败步骤判定。')]
# historical used subject cards
used=set()
for p in [ROOT/'evals/method_binding_efficacy_v1/pool.json',ROOT/'evals/method_binding_efficacy_v2/goldset_candidates.json',ROOT/'evals/method_binding_efficacy_v3/dev_calibration_v1/dev_candidates.json']:
 if not p.exists():continue
 j=json.loads(p.read_text()); cases=j.get('cases') or j.get('rows') or {}
 for c in cases.values():
  mid=c.get('subject_method_id') or (c.get('method_ref','').removeprefix('method:') if c.get('method_ref') else None)
  if mid:used.add(mid)
# old task hashes
oldtexts=set()
for p in [ROOT/'evals/method_binding_efficacy_v1/pool.json',ROOT/'evals/method_binding_efficacy_v2/goldset_candidates.json',ROOT/'evals/method_binding_efficacy_v3/dev_calibration_v1/dev_candidates.json']:
 if not p.exists():continue
 j=json.loads(p.read_text()); cases=j.get('cases') or j.get('rows') or {}
 for c in cases.values():
  t=c.get('task') or c.get('trigger')
  if t:oldtexts.add(t)
oldhash={sha(t.encode()) for t in oldtexts}
rows=[]
for i,(fam,sub,src,task,shared,purpose) in enumerate(CH,1):
 assert sub not in used,(sub,'subject reused'); assert sha(task.encode()) not in oldhash; hits=[p for p in FORB if re.search(p,task)]; assert not hits,(i,hits)
 c=card(sub); carrier='RESULT.md 摘要：'+c['description']
 rows.append({'case_id':f'v3h-B{i:02d}','kind':'challenge','family':fam,'intended':'SKIP','subject_method_id':sub,'source_method_id':src,'task':task,'carrier':carrier,'shared_surface':shared,'purpose_divergence':purpose,'card':card_text(c),'card_sha256':c['sha256'],'anti_leak_hits':hits})
for i,(sub,task,carrier_text) in enumerate(AP,1):
 assert sub not in used,(sub,'subject reused'); assert sha(task.encode()) not in oldhash; c=card(sub)
 rows.append({'case_id':f'v3h-A{i:02d}','kind':'apply_reverse_risk','family':'reverse_risk_apply','intended':'APPLY','subject_method_id':sub,'source_method_id':sub,'task':task,'carrier':'RESULT.md 摘要：'+carrier_text,'shared_surface':'carrier distractor','purpose_divergence':'task positively matches subject Method; carrier is related distractor','card':card_text(c),'card_sha256':c['sha256'],'anti_leak_hits':[]})
assert len(rows)==24 and len({r['subject_method_id'] for r in rows})==24 and len({r['task'] for r in rows})==24
for r in rows:r['opaque_id']=sha(('v3-holdout|'+r['case_id']).encode())[:12]
order=list(range(24));random.Random(SEED).shuffle(order);present=[rows[i] for i in order]
out={'schema':'subject-binding-v3-holdout/v1','seed':SEED,'source_dev_result_sha256':sha((ROOT/'evals/method_binding_efficacy_v3/behavior_protocol_v2/RESULT.json').read_bytes()),'cases':{r['case_id']:r for r in rows}}
(H/'candidates.json').write_text(json.dumps(out,ensure_ascii=False,indent=1)+'\n')
sealed={'schema':'subject-binding-v3-holdout-sealed/v1','present_order':[r['opaque_id'] for r in present],'cases':{r['opaque_id']:{k:r[k] for k in ('case_id','kind','family','intended','subject_method_id','source_method_id','purpose_divergence')} for r in rows}}
(H/'sealed.json').write_text(json.dumps(sealed,ensure_ascii=False,indent=1)+'\n')
lines=['# Subject-Binding v3 confirmatory holdout blind sheet','','Judge whether the Method card is applicable to the task. Return APPLY or SKIP and one concise Chinese reason comparing task purpose with Method purpose.','']
for n,r in enumerate(present,1):lines += [f'## {n}. {r["opaque_id"]}','','TASK','',r['task'],'','METHOD CARD','',r['card'],'']
(H/'BLIND-SHEET.md').write_text('\n'.join(lines))
for b in range(3):
 chunk=present[b*8:(b+1)*8]; q=[f'# Blind batch {b+1}/3','', 'Return one JSON object per case with opaque_id, verdict APPLY|SKIP, and one-line Chinese reason comparing task purpose with Method purpose.','']
 for n,r in enumerate(chunk,1):q += [f'## {n}. {r["opaque_id"]}','','TASK','',r['task'],'','METHOD CARD','',r['card'],'']
 (H/f'blind_batch_{b+1}.md').write_text('\n'.join(q))
print('rows',len(rows),'challenges',sum(r['kind']=='challenge' for r in rows),'apply',sum(r['kind']!='challenge' for r in rows),'anti_leak',sum(bool(r['anti_leak_hits']) for r in rows if r['kind']=='challenge'),'fresh_subjects',sum(r['subject_method_id'] not in used for r in rows))
print('sheet_sha256',sha((H/'BLIND-SHEET.md').read_bytes()))
