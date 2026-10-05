from __future__ import annotations
import hashlib, json, pathlib, random, re

HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
METHODS=ROOT/'data'/'methods'
V1=ROOT/'evals'/'method_binding_efficacy_v1'/'pool.json'
IQ=ROOT/'evals'/'instrument_qualification_v1'/'iq_candidates.json'
PREREG=HERE/'GOLDSET-PREREG.md'
SEED=20261006

def sha(b:bytes)->str: return hashlib.sha256(b).hexdigest()

def card(mid:str)->dict:
    raw=(METHODS/mid/'METHOD.md').read_text(encoding='utf-8')
    m=re.match(r'^---\n(.*?)\n---\n(.*)$',raw,re.S); assert m,mid
    meta,body=m.groups()
    def s(k):
        x=re.search(rf'^{k}:\s*(.+)$',meta,re.M); return x.group(1).strip() if x else ''
    def sec(k):
        x=re.search(rf'## {re.escape(k)}\s*\n(.*?)(?=\n## |\Z)',body,re.S); return x.group(1).strip() if x else ''
    d={'method_id':mid,'name':s('name'),'description':s('description'),'trigger':sec('Trigger'),'body':body.strip(),'content_sha256':sha(raw.encode())}
    assert d['name'] and d['description'] and d['trigger']; return d

def grams(t):
    t=re.sub(r'\s+','',t); return {t[i:i+2] for i in range(len(t)-1)}
def ov(a,b):
    A,B=grams(a),grams(b); return len(A&B)/min(len(A),len(B)) if A and B else 0.0

B=[
('anchor-evidence-to-instance-lifecycle-window-fffe781df7d0','anchor-process-verification-on-deployment-identity-1a2a8ee84ad1','一个受管服务刚完成重启，部署记录已经给出 runtime_root、git_head；现在只需要从当前进程列表验证所有目标实例是否运行在该部署身份上。没有要解释的跨代日志或历史连接证据。','任务目的是重启后的进程身份落地验证；subject 方法的目的是跨进程生命周期的证据窗口切分与同进程复现。'),
('anchor-first-claim-audit-81071f5c9dc1','audit-report-by-resolving-cited-pointers-4cbbd66a7689','需要审查一份报告，其中所有待核验事实都已经附有 commit/hash/URL/内部 ID；目标是逐个解析这些指针并给出证实、不可核验或证伪。报告不含需要优先刷新排序的 live 状态快照。','任务目的是逐指针 provenance 解析；subject 方法专门先筛持久状态锚点以处理报告时效漂移。'),
('anchor-history-sweep-before-cross-branch-reproduction-f37203595eca','bind-tree-reading-gates-to-artifact-ref-worktree-ece00051f244','某门禁脚本依赖只存在于分支 X 的 artifact；当前 cwd 在分支 Y，直接运行会报 working tree 找不到文件。任务是先把执行上下文绑定到 artifact 所属 ref/worktree 再运行门禁；并不存在文件缺一族锚点的 checker 断言。','任务目的是选择正确 worktree/ref 执行已有 gate；subject 方法只在 checker 声称文件缺锚点且需判 stale-contract vs regression 时适用。'),
('anchor-on-self-report-then-probe-gaps-003c0af478b6','binary-intervention-sufficiency-gate-7631f80e335c','用户问还是连不上要不要重启。系统没有 authoritative status/dashboard 可用，但监督者显示进程 running，且公网端到端探测得到应用级 HTTP 303。需要据此决定是否重启。','任务不存在权威 self-report 工具；应由最小事实对裁决二元干预，而不是以 self-report healthy/status 为主判据。'),
('anchor-on-unique-identifier-to-find-mechanism-ae14900fecb5','async-action-terminal-ledger-first-7f9a435b6e99','上轮已经发起异步 restart，action_id 与专属台账路径都在手。用户只问动作最终是否成功以及为什么没反馈；不需要查这个 ID 在代码里由谁生产或消费。','任务目的是读取既知 action 的终态并核反馈链；subject 方法用于未知机制的 producer/consumer 定位。'),
('anchor-sufficiency-stop-959b50a21a4c','answer-terse-ref-from-authoritative-goal-record-bound-recovery-f5a3ce3d72c2','用户说把前两个收口项完成；当前对话缺少那个清单，但 active Goal 回执已经列出恰好两个对应条目、各自完成时间，且 open=0。需要直接映射并回答。','权威 Goal 已一次解决指代；subject 方法面向 memory/docs 检索型 grounding，不应再引入额外检索。'),
('anchor-verification-over-narrative-recovery-73fa76a07438','authoritative-record-first-when-preview-truncated-0155675ee421','用户用唯一 EVO ID 引用一条已批准记录并要求按规格继续；records 搜索只返回截断预览，但持久台账可按该 ID 取全文。任务是先取完整权威记录再执行。','任务目的是按唯一 ID 恢复权威规格全文；subject 方法针对过去建议是否落实而把旧报告降级为声明清单逐锚验证。'),
('assertions-as-spec-first-for-behavior-edits-c1f836aa31cd','bulk-edit-from-displayed-literal-anchor-free-per-surface-verify-95849638b2f5','要把同一个版本号从旧值改成新值，旧字面量在多个文件中出现；预检 grep 已显示各目标行。目标是从这些已显示的字面行派生替换并逐表面复查，没有指标分母、行为语义或测试期望需要重新定义。','任务是多表面字面量迁移；subject 方法针对行为/指标契约变更，测试断言才是规范。'),
('async-wait-on-pipeline-conclusion-not-artifact-03a2fa7c25cb','bounded-probe-before-blocking-retry-e3e7b0a91b65','上轮 git fetch 挂死；现在到点决定是否重试。需要先对 remote host 做一条不超过 8 秒的网络探针，判断传输层是否恢复，再决定是否执行阻塞式 fetch。','任务是阻塞网络重试的故障分类；subject 方法只适用于等待异步 pipeline 终态/产物。'),
('attach-feasibility-gate-then-authoritative-config-42e640eda0c3','binding-verify-config-first-probe-86ba90942add','浏览器重启后要验证 CDP binding 是否仍一致，任务上下文已明确 .env 记录真实端口和 TARGET_ID；应先读 .env 再按值探测。当前没有 connection refused，也不是判断能否接入。','任务目的是已知配置源上的重绑一致性验证；subject 方法首先处理 connection refused 下的接入可行性。'),
('attribute-suite-failures-via-touched-set-and-clean-head-worktree-8d92c40cb6dc','complete-failure-inventory-before-root-cause-ce230cde7fa6','CI 失败日志在 traceback 中途被截断，连 short test summary 都没看到。当前唯一目标是先从完整日志钉死全部 FAILED/ERROR 清单与数量；尚未进入这些失败是不是本次 diff 引入的归因阶段。','任务当前缺的是失败全集；subject 方法是在失败集合已知后用 touched-set 与 clean HEAD 对照做因果归因。'),
('audit-closure-via-transition-event-receipts-not-artifact-grep-da92ba3b84c6','audit-duplicates-via-unfiltered-timeline-and-controlflow-boundary-340f7604d311','要审计一次会话为什么出现重复工具调用；会话经历 wake、compact 和 handoff，需要先拉完整未过滤事件流并定位控制流边界。问题不是某 lifecycle 是否完成，也不是统计 save/use/activate 阶段转移。','任务目的是重复动作的时序/控制流归因；subject 方法用于生命周期闭环与阶段转移证明。'),
('authority-contract-before-managed-mutation-62e4436f179e','binding-drift-preflight-before-gated-service-mutation-e6f2166d36f7','工具契约已经明确模型拥有 restart 权限、没有 operator-only 发布动作；但部署记录 git_head 与当前 HEAD 不一致，且并行会话留下 dirty 增量。任务是做 binding drift preflight，避免变更被 fail-closed。','权限归属已经无歧义；任务真正未知量是部署/工作区绑定漂移，subject 的 authority-contract 前置不再是决定性方法。'),
('batch-complete-required-fields-on-parameter-rejection-71b35b88bd44','bare-id-state-reconcile-before-transition-retry-588019de930e','一个 complete 动作此前已经发起，结果存疑；当前有唯一 action ID。需要先按裸 ID 取最新状态决定是否已经完成，而不是处理 requires evidence/reason 参数缺失。','任务目的是避免重复状态迁移；subject 方法只处理首次调用或明确参数缺失拒绝后的字段补全。'),
('binding-identity-gate-before-destructive-ops-9e1d9ef8f671','binding-verify-config-first-probe-86ba90942add','要验证重启后的 CDP 端点与 TARGET_ID 是否仍匹配，且 .env 已给连接参数；没有 kill/清理动作，也不存在把端口误当 PID 的风险。','任务是连接绑定验证；subject 方法专用于破坏性操作前确认数字 ID 的实体类别与归属。'),
('bound-verification-output-to-survive-truncation-5879c1e4cca7','bounded-chunk-write-verify-for-long-file-artifacts-45c00c2ebf00','要通过 shell heredoc 写一份约 120 行文档；历史上出现 exit 0 但文件只写了 8 行的输入截断。任务是分块写入并逐块核行数；不是读取 pytest/命令输出被截断。','任务风险是写入传输静默截断；subject 方法处理的是验证命令输出太长导致关键 summary 被截断。')]

C=[
('anchor-evidence-to-instance-lifecycle-window-fffe781df7d0','同一份运行日志跨过了几次服务重启。我已经拿到当前实例的 pid 和启动时刻，现在要判断只在新进程里出现的连接缓存异常是否仍能复现。','需要用当前实例身份切出证据窗口，并在当前进程内验证故障。'),
('anchor-history-sweep-before-cross-branch-reproduction-f37203595eca','一致性检查说某文件少了一整组标记；直接搜这个文件一个都找不到。我要判断这些标记是这次分支改没的，还是契约早就陈旧。','文件对锚点家族零命中，需要跨已知历史 refs 判定从未存在还是本次回归。'),
('anchor-on-self-report-then-probe-gaps-003c0af478b6','用户只问系统现在健不健康。系统本身已经有一个权威状态接口直接返回 healthy/status，我需要决定是否还值得展开更宽的诊断。','权威 self-report 已直接覆盖健康问题，应先以其状态字段作主判别。'),
('assertions-as-spec-first-for-behavior-edits-c1f836aa31cd','我要调整一个已有指标的分母与相关说明文字，测试目录里已经有对这个比率和 note 的精确期望，但我还没读这些断言。','这是既有行为/指标口径修改，测试断言是当前契约与修改面。'),
('async-wait-on-pipeline-conclusion-not-artifact-03a2fa7c25cb','CI 在后台执行，目标文件只有流水线成功才会生成。我正准备每隔几十秒检查一次文件是否出现，但流水线自身的 run 结论其实可查询。','失败是吸收态，必须先查 pipeline conclusion，不能只等产物存在。'),
('attribute-suite-failures-via-touched-set-and-clean-head-worktree-8d92c40cb6dc','本轮代码改完后定向测试全绿，但更大测试集出现几项失败。我需要判断这些失败是这次改动引入，还是当前基线本来就有。','应先将失败触面与本次 touched set 求交，再用 clean HEAD 对照做单变量归因。'),
('authority-contract-before-managed-mutation-62e4436f179e','我要在带 generation 的受管 desired-state 系统上做 publish/restart，但当前只知道模型工具面有 status/restart，不确定发布动作是不是只能由 operator 完成。','在受管变更前应先从 schema/注释确认动作权限归属。'),
('bound-verification-output-to-survive-truncation-5879c1e4cca7','我只想确认几个已知测试到底过没过，但 pytest 会吐出大量 warning，之前工具窗口把最后的 summary 和退出码截掉了。','应主动把验证命令塑造成短输出，保留 summary/exit code 以抵抗输出截断。')]

A=['anchor-narrow-wiring-at-construction-site-7f3ff30de391','anchor-quoted-ui-label-to-its-data-source-4ae2f64ced6c','artifact-symbol-lineage-before-mechanism-reading-e22289ec79cf','async-action-terminal-ledger-first-7f9a435b6e99','attribute-artifact-via-unique-token-before-impl-deep-read-28d50e49311f','authoritative-artifact-first-then-live-contract-probe-6867db304150','bare-citation-anchor-not-path-guess-c0caae461a97','bounded-chunk-write-verify-for-long-file-artifacts-45c00c2ebf00']
D=[
('anchor-narrow-wiring-at-construction-site-7f3ff30de391','async-wait-on-pipeline-conclusion-not-artifact-03a2fa7c25cb','一个 CI workflow 正在后台跑，成功后才会生成 release artifact；任务只是查询 run conclusion 并在失败时读失败日志，不涉及 factory 装配或 settings 接线。'),
('anchor-quoted-ui-label-to-its-data-source-4ae2f64ced6c','binding-identity-gate-before-destructive-ops-9e1d9ef8f671','用户要求终止两个数字标识，但目前不知道它们是 PID 还是端口；任务是先做身份映射再决定是否 kill，不涉及任何 UI 文案或前后端数据源。'),
('artifact-symbol-lineage-before-mechanism-reading-e22289ec79cf','batch-complete-required-fields-on-parameter-rejection-71b35b88bd44','第一次调用 closure API 被明确拒绝为缺少 evidence 与 reason；任务是一次补齐必填字段后重试，不需要归因任何日志 artifact 的写入者血缘。'),
('async-action-terminal-ledger-first-7f9a435b6e99','bulk-edit-from-displayed-literal-anchor-free-per-surface-verify-95849638b2f5','要把版本号在 pyproject、源码常量和 README 三个表面同步替换；预检 grep 已给出每个完整字面行，任务是替换并逐表面验证，不存在异步 action_id。'),
('attribute-artifact-via-unique-token-before-impl-deep-read-28d50e49311f','anchor-sufficiency-stop-959b50a21a4c','用户用一句很短的回指继续之前讨论，首次 memory 检索已经返回当天精确主题锚点；任务是停止继续检索并直接组织回答，不存在来源不明 artifact。'),
('authoritative-artifact-first-then-live-contract-probe-6867db304150','complete-failure-inventory-before-root-cause-ce230cde7fa6','CI 日志视图明显截断且没有 short test summary；当前只需要从完整日志固定全部 FAILED/ERROR 清单，不是在核对注册表或配置条目的 live contract。'),
('bare-citation-anchor-not-path-guess-c0caae461a97','binary-intervention-sufficiency-gate-7631f80e335c','用户报告外部访问失败并问是否要重启；监督者进程存活且公网端到端请求返回应用级 303，任务是据此否决重启并转查客户端路径，不涉及裸文件名引用。'),
('bounded-chunk-write-verify-for-long-file-artifacts-45c00c2ebf00','authority-contract-before-managed-mutation-62e4436f179e','需要在受管 desired-state 系统执行 publish/restart；工具 schema 只暴露 status/restart，源码注明 desired 由 operator 发布。任务是先判动作权限归属，不涉及长文件写盘。')]

def card_text(c): return f"name: {c['name']}\nmethod_id: {c['method_id']}\ndescription: {c['description']}\n\n{c['body']}"
oldtexts={c['trigger'] for c in json.loads(V1.read_text())['cases'].values()}|{c['trigger'] for c in json.loads(IQ.read_text())['cases'].values()}
oldhash={sha(x.encode()) for x in oldtexts}
oldsubjects={c['method_ref'].removeprefix('method:') for c in json.loads(V1.read_text())['cases'].values()}
cases=[]
def add(cell,i,subject,task,intended,source,purpose):
    c=card(subject); assert subject not in oldsubjects; tsha=sha(task.encode()); assert tsha not in oldhash
    cases.append({'case_id':f'sb2-{cell}{i:02d}','cell':cell,'subject_method_id':subject,'task':task,'task_sha256':tsha,'intended':intended,'construction_source':source,'purpose_divergence':purpose,'card':card_text(c),'card_sha256':c['content_sha256'],'task_vs_description_overlap':round(ov(task,c['description']),4),'task_vs_trigger_overlap':round(ov(task,c['trigger']),4)})
for i,mid in enumerate(A,1): add('A',i,mid,card(mid)['trigger'],'APPLY',mid,'self-trigger positive control')
for i,(s,src,t,p) in enumerate(B,1): add('B',i,s,t,'SKIP',src,p)
for i,(s,t,p) in enumerate(C,1): add('C',i,s,t,'APPLY',s,p)
for i,(s,src,task) in enumerate(D,1): add('D',i,s,task,'SKIP',src,'cross-domain negative control')
assert len(cases)==40 and len({c['task_sha256'] for c in cases})==40
assert {x:sum(c['cell']==x for c in cases) for x in 'ABCD'}=={'A':8,'B':16,'C':8,'D':8}
assert all(c['construction_source']!=c['subject_method_id'] for c in cases if c['cell']=='B')
for c in cases: c['opaque_id']=sha(('sb2-v1|'+c['case_id']).encode())[:12]
order=list(range(40)); random.Random(SEED).shuffle(order); presented=[cases[i] for i in order]
psha=sha(PREREG.read_bytes())
cand={'schema':'subject-binding-efficacy-v2-goldset/v1','prereg_sha256':psha,'seed':SEED,'cells':{'A':8,'B':16,'C':8,'D':8},'old_task_exact_reuse':0,'old_subject_reuse':0,'cases':{c['case_id']:c for c in cases}}
sealed={'schema':'subject-binding-efficacy-v2-sealed/v1','prereg_sha256':psha,'seed':SEED,'present_order':[c['opaque_id'] for c in presented],'cases':{c['opaque_id']:{k:c[k] for k in ('case_id','cell','intended','subject_method_id','construction_source','purpose_divergence','task_sha256','card_sha256','task_vs_description_overlap','task_vs_trigger_overlap')} for c in cases}}
(HERE/'goldset_candidates.json').write_text(json.dumps(cand,ensure_ascii=False,indent=1))
(HERE/'goldset_sealed.json').write_text(json.dumps(sealed,ensure_ascii=False,indent=1))
lines=['# Subject-Binding Efficacy v2 - Fresh Goldset blind sheet','',f'seed={SEED}; 40 cases.','','Score APPLY or SKIP and give one line comparing task purpose with Method purpose.','']
for i,c in enumerate(presented,1): lines += [f'## {i}. {c["opaque_id"]}','','TASK','',c['task'],'','METHOD CARD','',c['card'],'']
(HERE/'GOLDSET-SHEET.md').write_text('\n'.join(lines))
(HERE/'score_template.jsonl').write_text('\n'.join(json.dumps({'opaque_id':c['opaque_id'],'verdict':'','reason':''},ensure_ascii=False) for c in presented)+'\n')
print('prereg',psha)
for n in ('goldset_candidates.json','goldset_sealed.json','GOLDSET-SHEET.md','score_template.jsonl'): print(n,sha((HERE/n).read_bytes()))
print('cells', {x:sum(c['cell']==x for c in cases) for x in 'ABCD'}, 'fresh_tasks=40/40', 'fresh_subjects=40/40', 'B_purpose=16/16')
