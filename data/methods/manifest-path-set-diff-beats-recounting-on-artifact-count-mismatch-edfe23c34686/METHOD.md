---
method_id: manifest-path-set-diff-beats-recounting-on-artifact-count-mismatch-edfe23c34686
name: manifest-path-set-diff-beats-recounting-on-artifact-count-mismatch
description: 核验『构建产物（wheel/压缩包/包清单）应含 N 个文件』的声称与源码树是否一致时，若首轮计数不匹配，不要在同一列举工具上换 glob 参数重数——pathspec 的 * 与 ** 语义互不稳定，会给出互相矛盾的第三个数，越数越散。产物自带的逐路径 manifest（如 wheel RECORD、tar 清单、lockfile）本身就是真值清单：立即改为排序后的路径集合 diff，一次动作同时给出计数判定与差异文件的身份；再由差异路径形态（如 _bundled/skills/...）定位其仓库内来源做 1:1 闭合。本集以 611(树)+68(顶层 skills 捆绑)=679(清单) 一步闭合，省去两轮无效重数。
aliases: wheel 文件数和源码树对不上, 数文件数越数越乱, 清单对账别再重数, 产物和代码树逐路径对账, 计数差怎么溯源
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:3f431997-95b2-4bc7-8c02-006e4b883e18:2:fe3177c9c895071d0b49
evidence_refs: learning:learn:a5f64702a79f
created_at: 2026-11-14T13:32:13.378498+08:00
updated_at: 2026-11-14T13:32:13.378498+08:00
---
## Trigger
需要验证构建产物声称的文件数/模块数/内容清单与源码树一致，且首轮计数出现不匹配（树上计数 ≠ 产物清单计数）

## Discriminator
产物 manifest 是逐路径显式清单且回执已可读出全部路径——差异 Δ 的身份可直接由两个路径列表的 diff 得出，无需先确定『正确的计数 glob』；若同一列举工具换参数后给出互相矛盾的计数（如 611/597/679 三者互斥），该矛盾本身就是证据：计数工具不是判别仪器，应弃计数改比身份

## Short path
- 读产物 manifest，一次取得完整路径列表（同时得到总计数与目录分布）
- 用语义明确的目录实数（find）取树内路径列表并排序，不用 pathspec glob 计数
- 对两个路径集合直接 diff：同时得到计数判定与 Δ 的具体文件身份
- 由 Δ 路径形态（包内前缀如 _bundled/...）定位其仓库内来源目录，对该子集做 1:1 路径对应闭合
- 结合候选 diff 已证构建配置零改动，判定 Δ 属既定构建行为，停止

## Stop conditions
- 路径集合 diff 为空，或 Δ 已全部溯源到具体来源目录且与未被候选改动的构建配置一致
- 产物无逐路径 manifest 可读（仅有总数声称）时本方法不适用，退回粗计数并声明精度
- Δ 路径在仓库任何位置都找不到来源（产物含树外内容）→ 转为内容来源/供应链审查，不再对账

## Verification
- Δ 的每个路径都能在来源目录一一对应（本集 68/68 全匹配）
- 计数闭合等式成立：树内计数 + 来源目录计数 = manifest 计数（611+68=679）
- 构建配置在候选 diff 中零改动（否则捆绑行为本身可能被本候选改变，闭合不成立）

## Counterexamples
- 产物含编译/改名输出（.pyc、minified bundle），路径与源码非 1:1：路径集合相等是错误不变量，应比较语义内容
- 树含未跟踪/生成文件而产物由 tracked 状态构建：对错误的树状态做集合 diff 会产生假差异，需先钉死构建输入状态
- 只需回答『某文件是否在产物中』时，单点 manifest grep 优于全量集合 diff
