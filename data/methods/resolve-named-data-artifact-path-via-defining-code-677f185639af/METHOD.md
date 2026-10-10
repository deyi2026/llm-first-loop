---
method_id: resolve-named-data-artifact-path-via-defining-code-677f185639af
name: resolve-named-data-artifact-path-via-defining-code
description: 当任务已归结为『读取/统计某个被先前记录按唯一文件名指认的运行时数据工件』（usage 台账、日志、状态文件），但基线记录只给了文件名没给完整路径、且工作区文件搜索未命中时：search miss 只说明索引未覆盖数据目录，不是工件缺席。此时存在一条必然成立的窄 provenance edge——写出/读取该文件的代码必须包含这个文件名字面量。直接 grep 源码字面量定位路径拼接与 config 默认值（如 methods_dir），按解析出的唯一路径一次性读取，再按基线卡给出的锚定时间戳过滤新增条目作答。禁止动作：全盘 find、猜测约定目录（~/.dotdir 类）、反复换措辞重查记录库。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:29051f9a-5267-4d1e-90b4-dcb43292cc41:0:b68ee9a66ee8359182f5
evidence_refs: learning:learn:2f2aacbedce4
created_at: 2026-10-08T23:06:48.519413+08:00
updated_at: 2026-10-08T23:06:48.519413+08:00
---
## Trigger
需要读取/统计一个被基线卡或诊断记录按唯一文件名指认的运行时数据工件，但其完整路径未知，且 workspace 文件搜索未命中；代码库在本地可 grep。

## Discriminator
文件名是唯一字面量（如 usage.jsonl），任何写/读它的代码必须包含此字面量——这在 search miss 的当下就已知；它把搜索空间从『整个文件系统』缩成『源码内一次 grep + 一次 config 路径解析』。同时 config 存在 methods_dir 之类的路径默认值，可唯一解析落点。

## Short path
- 明确未知量只有两个：工件实际落点、基线时间戳之后的新增条目（基线卡已给出计数锚点）
- 把 search miss 解读为索引覆盖限制（数据目录不入索引），不转入文件系统枚举或路径猜测
- grep 源码中的文件名字面量 → 立即命中写入/读取函数与路径拼接（store 的 self._dir / 'usage.jsonl'）
- 读 config 的路径默认值并核对 runtime 覆盖 → 解析出唯一候选路径
- 按该路径一次性读取台账，按基线时间戳过滤新增并作答；可用事件流交叉验证无并发自然任务检索

## Stop conditions
- 已按 config 解析路径读到台账并完成基线前后计数 → 直接作答，停止
- 字面量 grep 在可用源码中无任何定义/写入点 → 工件属外部服务或动态命名，此时才升级为宽发现

## Verification
- 确认读到的文件路径与代码+config 解析结果一致（methods_dir/usage.jsonl），而非同名巧合文件
- 台账条目计数与最新时间戳须与基线卡声称的数值对得上（本例 6 条/10-07），不符则怀疑读错 store 或存在并发写

## Counterexamples
- 工件由本地代码库之外的系统产出（远端服务/托管存储）：grep 定义不可得，应走该服务的 API/文档
- 文件名是模板化/带时间戳的动态名，或路径仅由环境变量拼出：字面量 grep 落空或大量误命中，应先读 config/env 解析逻辑
- 文件搜索直接命中工件：直接读取即可，无需代码考古
- 基线记录已给出完整限定路径：按 provenance 直接读，跳过本方法
