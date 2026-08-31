"""trace_leak：agent 轨迹泄漏根治组件包（spec 5.2/5.3/5.4，design CM/CG/DD）.

模块清单：
- leak_events        五类泄漏事件统一出口 + 隔离区（dead/ 风格）
- invariant          溯源标记恒等式校验（落盘点共享）
- ingress_token      人类输入通道哨兵凭据（进程内不可伪造）
- channel_whitelist  通道白名单声明式单一真相源
- user_ingress_guard user 身份写入守卫（双点挂载核心）
- leak_detector      build 期标记失真/通道越权检测
- trace_signature    轨迹结构特征兜底（默认仅告警）
- outbound_trace_fetch 外部轨迹带外化检索（reference 层）
"""
