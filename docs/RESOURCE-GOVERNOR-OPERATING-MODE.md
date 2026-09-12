# Resource Governor 运行口径声明（v0.6.14）

> 本文回答一个问题：**RG 今天到底"管"什么、不管什么。**
> 依据：`src/llm_loop/resources/`（RG-0~3E）、`factory.py:1236` 接线、`llm/client.py:672-769` 守卫。
> 审计方法：全源码 grep 消费方（2026-09-12，`ce363578`）。

## 一、两套口径，性质不同

| 层 | 阶段 | 性质 | 生效范围 |
|---|---|---|---|
| **RG-1 租约** | lease/concurrency | **真执行（enforcement）** | 仅后台 learning plane：background deliberation 并发=1、前台屏障 |
| **RG-3B/3C/3D/3E 事实** | transport/settlement/ledger/vendor | **shadow（observation-only）** | 全部 provider 调用路径：观察、记账、投影，**永不影响行为** |

## 二、shadow 口径的硬性不变量（代码守卫，非口头承诺）

1. **传输永不因 shadow 阻断**：`llm/client.py` 中所有 shadow 观察（response/usage/error/settlement）
   均包裹 `except Exception → logger.debug`（"shadow can never affect provider behavior"）。
   观察器抛任何异常，provider 调用照常返回。
2. **shadow 事实无 admission 消费方**：全源码审计确认 `ledger_projection` / vendor adapters 的产出
   仅在 `resources/` 模块与 factory 接线内流转；admission/routing/fallback/enforcement 均不读取
   （`resources/__init__.py` 模块契约明文）。
3. **未知容量≠无限**：`ResourceGovernor` 对未注册 limit 的 key 返回 `REQUIRED_FACT_UNKNOWN`，
   不默认放行。
4. **不越权推断内容**：RG 不看 prompt、不判任务内容/质量/完成度/信任策略——这些属模型与
   Method 体系职责。

## 三、为何 shadow 先行（口径依据）

RG-3x 的存在目的是积累**可信的机械事实**（用量、成本、限流、跨会话结算投影），为将来任何
enforcement 决策提供事实底座。在其准确性与覆盖率未被 qualification 验证前：
- 不把观察事实写成拦截依据——错误的成本核算直接拦截会造成不可回滚的业务损失；
- 不把 shadow 事实喂给模型——避免模型基于未审计事实自我限流；
- 升级到 enforcement 必须走 qualification → canary → 分级启用三步，与 Method 生命周期同纪律。

## 四、当前真执行的唯一路径（如实声明）

RG-1 在 learning plane 的使用是**机械性**的：`learning_plane.py:99,136,194,306`——
后台 deliberation 并发上限、`higher_priority_active` 前台屏障（真人活跃时后台让位）。
它不判断"该不该想"，只做"有没有空位"。主循环与 subagent 路径当前**不经 RG-1 准入**
（`resource_governor=None` 可选注入，默认仅 learning plane 生效）。

## 五、复核方式

任何人可用以下命令复核本声明：
```bash
grep -rn "shadow" src/llm_loop/llm/client.py          # 守卫位置
grep -rn "resource_governor\." src/llm_loop --include="*.py" | grep -v test  # RG-1 真实消费方
grep -rn "ledger_projection" src/llm_loop --include="*.py" | grep -v "resources/"  # shadow 事实越界消费=0
```
