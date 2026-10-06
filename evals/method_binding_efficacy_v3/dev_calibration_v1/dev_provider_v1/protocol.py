from __future__ import annotations
import re
MODELS={
 'strong':{'bare':'deepseek-v4-flash','canonical':'deepseek/deepseek-v4-flash'},
 'weak':{'bare':'cognilocal/qwen3.8-flash-next','canonical':'cognilocal/qwen3.8-flash-next'},
}
ARMS={'C0':None,'C1':'1'}
BINDING_ENV='LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL'
BINDING_MARKER='lfl-method-applicability-subject-binding/v1'
VERDICT_RE=re.compile(r'APPLICABILITY_VERDICT\s*[:：]\s*(APPLY|SKIP)\b')
FORMAL_PROMPT='''下面给出一个执行代理的【当前任务】，以及一张候选【Method 卡片】全文。\n\n【当前任务】\n{task}\n\n【候选 Method 卡片】\n{card}\n\n请判断该 Method 是否适用于当前任务，然后只输出一行裁决，不要输出任何其他内容。格式必须严格是：\nAPPLICABILITY_VERDICT: APPLY | SUBJECT: <本任务所围绕的核心对象，不超过20字> | REASON: <不超过40字>\n或\nAPPLICABILITY_VERDICT: SKIP | SUBJECT: <本任务所围绕的核心对象，不超过20字> | REASON: <不超过40字>\n'''
PREFLIGHT_PROMPT='只输出 PREFLIGHT_OK，不要调用任何工具，也不要输出其他内容。'
def parse_verdict(text:str)->str:
 m=VERDICT_RE.search(text or '')
 return m.group(1) if m else 'OTHER'
