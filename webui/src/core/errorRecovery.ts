/** Advice only: never automatically resubmit a possibly completed tool run. */
export function errorRecoveryHint(error: string): string {
  if (/401|403|unauthorized|API.?key|认证|鉴权/i.test(error))
    return "请检查登录状态或模型密钥与权限，修正后再重试；输入「继续」不能修复认证错误。";
  if (/429|rate.limit|限流|额度|余额/i.test(error))
    return "请稍后重试，或检查模型额度；避免连续重复发送。";
  if (/400|reasoning_content|参数|模型不存在/i.test(error))
    return "请检查所选模型与配置，并保留错误详情用于排查；直接输入「继续」可能仍会失败。";
  if (/timeout|超时|网络|连接|中断|502|503|504/i.test(error))
    return "先确认任务是否仍在运行。可重新加载会话查看最新结果；确认任务已结束后，可输入「继续」接着处理，避免重复提交已执行的操作。";
  return "请保留错误详情并查看任务状态；确认任务已结束后，可输入「继续」接着处理。若再次报错，请检查模型配置。";
}
