# CTP 注册表原型设计边界（B5 / TASK-e9f14fe1-009）

- 对应规范：docs/SPEC-20261123-cooperative-target-protocol-v0.9.md §6 R-1..R-6（v0.9.2）
- 超期处置依据：docs/SPEC-20261123-CTP-tbd-resolutions-proposal.md §G5（PROP-0.2，**提案，非决议**）
- 执行期暂定值：PLAN-20261123 §13.1 D-08（Ed25519 + 确定性 JSON；**偏离**原"确定性 CBOR"建议）
- 范围：本地原型，覆盖 R-1..R-6 的语义与拦截行为；不含在线服务、密钥治理与分发（见 §5）

## 1. 已实现 → 规范条目映射

| 条目 | 要求 | 实现位置 | 拦截行为（稳定 code） |
|---|---|---|---|
| R-1 | 记录最小字段集 + 确定性 JSON | record.py: RegistryRecord（from/to 键排序、无空白） | missing_field / type_error / value_out_of_range / timestamp_missing_timezone 等 |
| R-2 | append-only、禁物理删除与改写、重放校验完整性 | store.py: RegistryStore（JSONL + sha256 哈希链） | 实现层无删除 / 改写接口；payload_tampered（改写行）、chain_broken（删行 / 重排 / 截断） |
| R-3 | 报废→墓碑终态、ID 禁止复用 | tombstone.py: Tombstone + store.append 写前检查 | tombstone_reuse（复用登记）、already_tombstoned、unknown_id |
| R-4 | 带版本与签名的离线快照、无网络独立校验 | snapshot.py（快照级 + 记录级两级 Ed25519） | missing_signature / signature_invalid / snapshot_invalid |
| R-5 | 绑定前必验签、查无签名记录拒绝绑定 | verify.py: bind_semantics（绑定序：链→存在→墓碑→验签→隔离） | no_signed_record / missing_signature / signature_invalid / tombstoned_id |
| R-6 | last_verified + period → 待复验；两级处置 | expiry.py: classify_expiry（G5 一级 / 二级） | quarantined_record（二级拒绝绑定）；timestamp_missing_timezone |

错误码体系复刻 ctp_contract/errors.py 风格：RegistryError(code, path, detail)，frozen dataclass，code 是稳定契约。

## 2. 执行期暂定值（D-08）声明

- **签名算法 = Ed25519**（cryptography 库），**序列化 = 确定性 JSON**（ensure_ascii + sort_keys + 无空白分隔符）。
- 签名载荷 = 载体对象"无 signature 字段的确定性 JSON"之 **sha256 摘要**（记录级与快照级同构）；换序列化器（如 CBOR 依赖就位后回切）不改此结构。
- 此为 PLAN §13.1 D-08 暂定值，**偏离**决策表原建议（Ed25519+确定性 CBOR），依据 = cbor2 未安装、cryptography>=43 已有；必须由用户 / 工作组确认的时点 = **B5 原型完成、对外签发格式定稿前**（本文件即该时点的输入之一）。

## 3. R-6 两级处置：按 PROP G5 提案实现（待 WG-RES 追认）

- 一级：age >= revalidate_period_days → pending_revalidation——可绑定、观测可用但禁入高精度决策（"禁入高精度"由读码器以 C-5 degradation_flag 表达，注册表不拦绑定）；
- 二级：age >= G5_QUARANTINE_PERIODS(=2.0) × period → quarantine——拒绝语义绑定、（规范侧）禁止几何互证参与；倍数 **2 来自提案文本**（"超期持续 ≥ 2 × 复验周期"），非实现发明；运行时派生态即提案所称"墓碑候选"标记（append-only 下不写持久字段，形式留工作组）。
- **边界语义自选并记录**：判定用 >=（到期当日即算超期）——SPEC 未定义边界，本实现取保守侧（宁可多标，不让过期数据静默进入高精度通道）。
- 追认前，二级拒绝的 RegistryError.detail 携带 "PROP-20261123-CTP-TBDG-0.2 ... pending WG-RES ratification" 标注；提案被否决时删除 quarantined_record 拦截并保留一级即可回退。

## 4. 数值纪律（零硬编码门槛）

- revalidate_period_days 是记录必填字段，**无默认值**；classify_expiry / bind_semantics 的 now 必填 keyword-only，**无隐式时钟**（测试与审计可复现）；
- 实现内仅有的数值常量：Ed25519 签名 64 字节、sha256 32 字节、GENESIS 全零链锚、G5 倍数 2.0——均为算法 / 提案结构常量，非门槛；
- test_no_hardcoded_period_defaults 以 dataclasses/inspect 反射断言上述无默认值事实（机检式防回归）。

## 5. 留给工作组 / 后续任务（TODO-G2 登记）

1. **R-6 强制等级终裁**（SPEC §14 开放项）：两级阈值与"墓碑候选"持久化形式；本原型实现按 §3 可回退。
2. **签名格式定稿**（D-08 确认时点）：对外签发格式（公钥编码 PEM/raw、签名封装、密钥轮换与多权威）；本原型只接受 cryptography 密钥对象，不做密钥治理。
3. **ID 位长 / 前缀格式校验**：随 C-1 [TBD-G]（G1 提案 48bit 逻辑 ID）裁决后补 target_id 格式校验；当前仅要求非空字符串。
4. **墓碑是否需要权威签名**：SPEC R-3 未要求，本原型未发明；若裁决要求，Tombstone 加签名字段并纳入链校验。
5. **公钥分发与信道防护**（T-5）：在线查询的可校验通道、快照分发链——超出本地原型。
6. **在线服务化**：当前为库形态 + 文件存储；多读者 / 单写者的进程模型与并发锁不在此层（单进程假设已在 store.py docstring 声明）。

## 6. 实现层收紧与已知边界（如实声明）

- **收紧 1**：append 拒绝无签名的 register 记录入库（SPEC 未规定；防未签名记录静默入档）。绕过 append 的直接文件写入仍可产生无签名行——由 bind_semantics 的 R-5 检查拦截（测试 test_unsigned_record_binding_refused）。
- **收紧 2**：同 ID 新 record_version 必须严格递增（append-only 的"更新"= 新事件）。
- **哈希链的定位**：防意外损坏与非特权篡改；**不防**能重写文件并重算全链的特权攻击者（T-2 D2）——防伪第一级是 Ed25519 记录签名（私钥离线），两级分工即 T-4a 与审计完整性的组合。
- **快照不含时效判定**：离线校验承诺"数据可信"（两级签名），不承诺"数据未过期"（R-6 需显式 now）。
- **时钟边界**：now 早于 last_verified（时钟回拨）按 OK 处理；回拨检测不在本层。
- 快照中墓碑 ID 的 register 历史不进 records（终态语义，防离线误用），完整历史仍在事件日志。
