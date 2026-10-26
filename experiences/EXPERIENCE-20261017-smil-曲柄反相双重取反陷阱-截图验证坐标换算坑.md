---
title: SMIL 曲柄反相双重取反陷阱 + 截图验证坐标换算坑
scenario: SMIL 自行车/机构动画：双侧曲柄踏板（踏板+脚+腿）反相蹬踏的实现与验证；以及截图验证动画时坐标系搞错缩放导致误判。
root_cause: ""
solution: 机构镜像件的反相用几何承担（对称局部坐标），begin 负偏移只用于与几何独立的元素；验证用数值测量（bbox 中心 vs 路径末端距离、双件间距恒定）而非视觉模型；像素差分前先确认 SVG 实际渲染尺寸换算裁剪窗口。
evidence: "修复前测量：两脚椭圆 bbox 中心全程重合、dFar≈52-65px（远腿踩空），远侧轨道矩阵相位 θ+180° 与局部偏移 −30 叠加（matrix a/b 采样证实）；删除远踏板组 begin=\"-0.6s\" 后：feetSep 恒=60px（2×曲柄半径30）、dNear/dFar=4-8px（脚心高于踏板轴6px设计量），像素差分确认车轮8.3/前轮8.2/曲柄18.2/躯干9.1/虚线30.5 均变化、太阳对照0.02。产物 pelican_bicycle_animation.svg，截图 data/e2e/pelican/pelican_fix_t1-3.png。"
tags: [svg, smil, animateTransform, 曲柄动画, 验证方法, playwright]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-17T14:49:36.957494+08:00"
updated_at: "2026-10-17T14:49:36.957494+08:00"
---

用嵌套 animateTransform 做曲柄踏板时：踏板组 = 外层绕中轴公转 rotate(θ) + 内层绕踏板轴自转 −θ 保持水平。若远侧踏板的局部几何已经画在中轴另一侧（如中轴(380,335)、踏板局部(350,335)，偏移为 −30），则它的公转动画绝不能再加 begin 负偏移实现反相——R(θ+180°)·(−30,0) = R(θ)·(30,0)，双重取反会让远踏板精确叠到近踏板上（视觉上"两脚同踩一个踏板"）。反相只能由几何镜像本身承担；只有纯关键帧路径动画（如腿部 d morph）才用 begin="-T/2" 反相。验证不要只靠视觉模型看截图（会把腿扇形误读为同踏板），用 getBoundingClientRect 采样脚椭圆中心 + getPointAtLength 取腿末端，距离和双脚间距（应恒为 2×曲柄半径）是确定性判据。另：Playwright 截图做像素差分时，先确认 SVG 实际渲染尺寸（svg width 属性=800px 时 scale=1，不是视口/800），再换算裁剪窗口，避免裁到画外得出"动画冻结"的假阴性。