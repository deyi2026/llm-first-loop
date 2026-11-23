# 不确定度声明模板（11.1-c）｜B2

读码器实现方在提交合规声明时，按本模板填 C-5 的 `uncertainty` 字段。本模板只规定**怎么填**，
不提供任何数值——数值必须来自 V2 精度实测（或实现方自己的误差预算推导），见 SPEC §0.2 与计划 K3。

## 1. 字段

| 字段 | 必填 | 含义 | 单位 |
|---|---|---|---|
| `model` | 是 | 不确定度模型标识（如传播方式 + 误差源清单的短名） | — |
| `k` | 是 | 覆盖因子（与 1σ 一起给出，缺一不合规） | — |
| `translation_1sigma_m` | 是 | 平移各轴 1σ | m |
| `rotation_1sigma_deg` | 是 | 旋转各轴 1σ | **deg**（C-5 口径） |
| `covariance_6x6` | 否 | 完整协方差；给出时以它为准 | m / **rad** |

顺序约定（写死在 `ctp_calib` 里）：`[tx, ty, tz, rx, ry, rz]`；旋转协方差用 rad，1σ 用 deg，
换算只在 `UncertaintyTemplate.covariance()` 一处发生。给出 `covariance_6x6` 时，1σ 仍必须填，
两者不一致以协方差为准并在声明里注明。

## 2. 填法（三步）

1. **定误差源**：把误差拆到可归因的项（角点定位、位姿解算、靶标制造公差、温度形变……），
   每项给 1σ 与传播关系；不允许只写一个"总误差"。
2. **算各轴 1σ**：由误差源按几何关系传播（力臂 × 角度误差要算进去，别只报角点像素噪声）。
3. **自检一阶近似**：用 `ctp_calib.check_first_order_validity` 把线性传播与蒙特卡洛对比；
   逐轴相对误差超过 5% 时，要么缩小声明的适用域，要么改用 MC 结果，**不许照抄线性结果**。

## 3. 自检

```bash
# 在 ctp/ 目录下
python -c "import sys; sys.path.insert(0,'src'); import ctp_calib as c, numpy as np, math; \
A=c.pose_matrix((0,0,1.2),(0,0,0,1)); B=c.pose_matrix((1,0.5,1.5),(0,0,0,1)); \
cov=np.diag([1e-6]*3+[math.radians(0.17)**2]*3); \
print(c.check_first_order_validity(A,B,cov,cov)['ok'])"
```

## 4. 禁止

- 禁止把本模板里的任何占位当成数值填进规范（TBD 只能由实测回执或工作组决议回填）；
- 禁止 `k` 与 1σ 只给一个；
- 禁止用"零不确定度"表示"很准"（C-5 校验器会判 `degenerate_uncertainty`）；
- 禁止在声明里写与实测不符的数字——V6 用 `k·√(u₁²+u₂²)` 交叉验证两家声明是否自洽。
