---
method_id: follow-error-named-remediation-to-subsystem-interface-568c647646cb
name: follow-error-named-remediation-to-subsystem-interface
description: 当失败回执/错误消息已明确命名失败检查所属子系统并给出补救动词（如 service_control 绑定校验失败、需 operator publish 新 generation）时，剩余未知量只有两个：补救子命令的准确参数签名、当前已发布状态值。应直接从该子系统自身的接口定义（argparse 源码或不含被拦动词的 --help）与只读状态命令（show）求解，而不是全库文本搜索补救动词或通读调用脚本的其他校验段；若含动词的命令被策略拦截，拦截本身证实这是 operator-only 动作，应改读接口定义而非继续试命令变体。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8264c548-85f1-4132-ad60-06764dbeb232:495:bb90339a99a896120477
evidence_refs: learning:learn:cca3e31367a7
created_at: 2026-09-18T12:57:36.664681+00:00
updated_at: 2026-09-18T12:57:36.664681+00:00
---
## Trigger
自动链/脚本的失败回执或错误消息中已出现'子系统名 + 补救动词'组合（如 service_control 绑定失败、需 operator publish exact desired generation），但准确执行参数与所需状态值尚未知，且用户/角色分工要求把最终命令交给操作者执行。

## Discriminator
进入扩散前，job 输出已明确给出：失败检查属于 llm_loop.runtime.service_control 的 desired deployment 绑定校验，且补救动作是 operator publish。这一当时已知事实把'所有可能相关的文件/脚本段'缩为两个可验证未知量——publish 子命令的 argparse 签名、store 当前 generation——分别由该模块源码与只读 show 直接回答，无需先做全库搜索或读调用脚本的无关校验段。

## Short path
- 读 job 输出/失败回执：确认链仍存活、卡点原因；记录消息中命名的子系统与补救动词（此步已含绑定失败的全部关键事实）
- 终止自动链并取消定时唤醒：在用户手动接手前清除会与其竞争的执行者
- 读该子系统的 argparse 定义（或不含被拦动词的 --help）：获得补救子命令的准确参数签名与 required 项
- 跑该子系统只读状态命令（show）：取得 CAS 所需当前值（如 generation=28），并借其附带的 git 输出判断当前 HEAD 与已发布绑定的先后关系、是否需要 checkout
- 组装 operator 命令并附绑定不变量（如 publish 与后续 verify 之间不得重建产物），连同已核实的现状一并交给用户执行

## Stop conditions
- 补救命令的参数签名与所需状态值（generation、code/runtime root）均已从子系统自身接口定义与只读状态输出双重确认
- 已确认无并发执行者（自动链已终止、定时唤醒已取消），操作序列含关键不变量说明并已交付用户

## Verification
- 对照 argparse 源码逐项核对所给命令的 flag 名与 required 属性（如 --expected-generation 为 int 且 required）
- 用只读 show 的当前 generation 推导 CAS 参数取值，确认无差一错误（当前 28 -> 发布 29）
- 确认失败原因归因闭环：show 输出的 git_head 与回执中 desired 绑定一致，证明是记录过期而非代码错误

## Counterexamples
- 调用脚本对子系统参数做了包装/翻译，脚本内部实际调用的函数签名与 CLI 不同——此时脚本调用点才是命令真值，只看 CLI argparse 会给出错误参数
- 错误消息只有泛化建议（'联系管理员'、'检查配置'）而未命名子系统与补救动词——没有可沿的因果边，此时回到状态检查或适度的宽发现才是对的
- 运行时根本不走该 CLI 而是直接 import 内部函数，CLI 虽存在但参数集/语义已分叉——需先确认真实调用路径再决定读哪份定义
