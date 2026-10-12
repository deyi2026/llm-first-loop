# 任务启动纪律：历史任务不自动重启（事故等价 fixture）
- **scenario**: 会话恢复/新会话开始时，面对已完成的历史任务或未完成任务（task frontier、后台 job）的启动决策
- **rule**: 已完成的过去任务一律不重新启动；未完成任务需启动/恢复时，必须先询问用户并获明确同意
- **root_cause**: 自动重启历史任务浪费资源且可能产生非预期副作用；重启决策权在用户
- **tags**: [任务管理, 后台任务, 用户确认, 会话恢复, 行为纪律]
- **note**: 本文件为不可解析文档事故等价 fixture——缺 front matter 起始标记 '---'（生产库 task-restart/err1210 文档同形态），from_md 抛 ExperienceParseError，检索扫描时被跳过并留痕