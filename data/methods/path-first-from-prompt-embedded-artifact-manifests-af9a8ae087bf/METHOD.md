---
method_id: path-first-from-prompt-embedded-artifact-manifests-af9a8ae087bf
name: path-first-from-prompt-embedded-artifact-manifests
description: 审核/核对类任务需要定位文稿、图片、源码时，若任务材料（图片哈希 manifest、文稿免责/来源列表）已枚举完整相对路径，直接按路径 path-query/ls/read，把『发现文件』阶段整个消除。两类已知搜索陷阱：filename glob 匹配不到目录名（返回空≠不存在）；裸 basename（如 runner.py）在含 .releases/ 镜像快照的仓库只命中旧版本噪声，核验必须钉在被审文档自己声明的主树路径。任一路径 404 或哈希不符才升级为搜索。本集 3 次 filename 搜索（1 次空 + 2 次镜像噪声）本可全部省去。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:909bedf5-1e9a-47a7-a902-70f8999e4d15:0:092002e864c87018f039
evidence_refs: learning:learn:a9b7ceca9297
created_at: 2026-10-14T21:45:19.840935+08:00
updated_at: 2026-10-14T21:45:19.840935+08:00
---
## Trigger
任务要求定位并核验一组 artifact（文稿/图片/源码文件），而提示或随附材料中已出现这些 artifact 的完整相对路径清单（哈希 manifest 的资产路径、来源与免责列表中的源文件路径）

## Discriminator
提示里是否已存在可直接 stat 的完整相对路径（含目录段的资产路径、明确列出的源码文件路径）。是 → 定位问题已解决，无需搜索；同时注意 filename 搜索不匹配目录名，basename 在多版本仓库会命中镜像/快照噪声

## Short path
- 从提示内嵌 manifest/来源清单提取所有待核验文件的完整相对路径；文稿本体路径由资产目录上推（去掉 assets 段拼文稿文件名）
- 逐一直接 path-query/stat 这些路径；命中即跳过全部 filename 搜索，随后做哈希一致性核验
- 源码事实核验只沿被审文档自己声明的主树文件路径 grep/读取，不读 .releases/ 快照或 scripts/ 下同名文件
- 全部路径命中且哈希一致后，直接进入内容核验（源码常量/逐字引用、图文对应、旧稿主题比对）并成稿

## Stop conditions
- manifest 全部路径存在且哈希一致、清单内源码事实核验完成 → 停止一切定位类操作，进入分析与成稿
- 某路径 404 或哈希不符且排除笔误后 → 才扩大到 filename/内容搜索定位真实文件

## Verification
- 复查最终报告引用的每个文件路径，确认均来自提示内嵌清单或由其目录直接推导，而非搜索噪声命中
- 确认所有事实核验依据只来自主树声明路径，未混入 .releases/ 快照或其他同名文件
- 若发生过任何搜索，回看其回执是否真的改变了下一步（无信息增益的搜索记为浪费）

## Counterexamples
- 提示只给哈希或裸文件名、无路径，或路径已移动/属于不可达环境 → 直接 path-query 会连环 404，先搜索定位才是正确第一步
- 任务目标本身就是全库版本普查、发现未知文件或路径已过期需重新发现 → 宽枚举是任务本体而非弯路，不适用本方法
- 内嵌路径指向的文件存在但内容与任务无关（清单过期）→ 仍需以内容搜索纠正，不能盲信路径
