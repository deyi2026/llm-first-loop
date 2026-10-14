---
method_id: figure-label-verification-via-coordinate-ocr-not-crop-assumptions-f744cab75889
name: figure-label-verification-via-coordinate-ocr-not-crop-assumptions
description: 核验 PDF/文档图像层内实际印刷的文字标签及其版面归属时：先确认文字不在文本层，导出嵌入的原始位图，再对整幅原图运行『返回文本框坐标+置信度』的独立 OCR，用坐标聚类完成区域归属。不要按假设的均匀网格先裁剪再复核——裁剪框把未验证的版面假设编码进证据，会把跨区文字（如状态框）误归属为标题并制造伪冲突；同一通道多次一致读取不构成独立验证，换引擎+坐标通道才算；冲突出现时先怀疑自己的裁剪/版面假设，再怀疑 OCR。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:6198b7b1-67ec-407c-8e94-f9f028f1f197:364:ce7d2d1d11c27c0ebb7f
evidence_refs: learning:learn:b782b4d73106
created_at: 2026-10-13T22:02:44.031931+08:00
updated_at: 2026-10-13T22:02:44.031931+08:00
---
## Trigger
需要核验某个 figure 图像层中印刷的文字标签（含每条文字属于哪个分格/标题栏/状态框的版面归属），且对图内关键词的 PDF 文本层检索为空（说明文字只存在于位图，必须走图像/OCR 通道）

## Discriminator
待解决的未知量是『文字的版面归属』而非『文字内容本身』，且原始整幅嵌入位图已导出在手——坐标返回型 OCR 可一步同时给出内容与位置；而任何预裁剪都先验地提交了一个未验证的网格假设。另一个已存在的事实：同一视觉通道的两次一致读取不增加证据独立性。

## Short path
- 从正文/图注文本定位目标 figure 的正确编号与所在页（文本层 grep 关键词），同时纠正引用中的编号错误
- 权威源 ID 已知时直接获取 canonical 文件（如 arXiv ID → curl PDF），不先枚举本地文件系统找现成副本或辅助脚本
- 环境缺库时一次性用 venv 安装（PEP 668 禁 system pip），避免反复试装
- 导出该页嵌入的原始图像对象（xref，全分辨率），而不是仅依赖低 DPI 整页渲染
- 对整幅原图运行返回 (x, y, text, conf) 的独立 OCR 引擎，按 y/x 坐标聚类把文字分入版面区域（标题带/状态带），不做任何预裁剪
- 与图注/正文语义交叉核对（如 WRITE/READ 标注的步骤集合应等于正文点名的步骤集合）后停止

## Stop conditions
- 坐标 OCR 的全部文本框与图注/正文语义互相印证，所有待核标签均有坐标与高置信度
- 目标文字在 PDF 文本层命中 → 直接用文本层结论，跳过 OCR
- 图为纯矢量、无可提取位图 → 退化为整页高 DPI 渲染后再做坐标 OCR

## Verification
- 复现：对原始嵌入图运行坐标 OCR，应得到稳定文本框集合；标题类标签的 y 坐标应聚成与分格行数一致的簇，状态类标签落在行间带
- 交叉验证：坐标归属结论与图注描述一致；若更换独立 OCR 引擎得到相同坐标结构，则此前冲突视为已消解且归因于裁剪假设而非 OCR

## Counterexamples
- 目标文字已在 PDF 可搜索文本层中 → 直接提取文本层，无需图像/OCR 通道
- 图为矢量绘图、无嵌入位图 xref → 无原始图可导出，只能整页高 DPI 渲染
- OCR 引擎只返回纯文本流、不返回坐标 → 坐标归属不可用，任何裁剪得到的结论必须标注为假设并另行验证
- 标签为竖排/旋转文字 → 简单 y 带聚类失效，需按文本框方向分组
- 任务关心图像视觉内容（物体、场景）而非印刷文字 → 本方法不适用
