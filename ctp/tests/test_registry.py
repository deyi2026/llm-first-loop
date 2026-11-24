"""ctp_registry 测试（计划 B5）：SPEC-20261123-CTP-0.9.2 §6 R-1..R-6 每条至少 1 正例 + 1 应拦负例。

纪律：
- 所有时间 / 周期参数显式给定（数值只作测试参数，不进规范层常量）；
- 应拦负例一律断言稳定错误码（RegistryError.code），不匹配消息文本；
- G5 两级处置按提案实现，断言 detail 携带"待 WG-RES 追认"标注。
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ctp_registry import (
    GENESIS_HASH,
    G5_QUARANTINE_PERIODS,
    KIND_REGISTER,
    KIND_RETIRE,
    ExpiryStatus,
    RegistryError,
    RegistryRecord,
    RegistryStore,
    StoreEvent,
    Tombstone,
    bind_semantics,
    build_snapshot,
    classify_expiry,
    compute_entry_hash,
    sign_record,
    sign_snapshot,
    verify_offline,
    verify_signature,
    verify_snapshot,
    write_snapshot,
)

KEY = Ed25519PrivateKey.generate()
PUB = KEY.public_key()
WRONG_KEY = Ed25519PrivateKey.generate()  # 模拟 D3 / 换权威场景
TZ = timezone(timedelta(hours=8))

BASE = dict(
    target_id="ORG-0001:00000001",
    object_ref="robot:r1",
    frame_ref="frame:r1/base",
    installed_on="2026-01-15",
    last_verified="2026-06-01T10:00:00+08:00",
    revalidate_period_days=30.0,
    record_version=1,
)


def make_record(**overrides) -> RegistryRecord:
    fields = dict(BASE)
    fields.update(overrides)
    return RegistryRecord(**fields)


def signed_record(**overrides) -> RegistryRecord:
    return sign_record(make_record(**overrides), KEY)


@pytest.fixture
def store(tmp_path: Path) -> RegistryStore:
    return RegistryStore(tmp_path / "registry.jsonl")


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ===================== R-1 记录与确定性 JSON =====================


class TestR1Record:
    def test_roundtrip_deterministic_json(self):
        """正例：签名记录 JSON 往返一致；序列化确定性（键排序、无空白、字节级可重复）。"""
        record = signed_record()
        line = record.to_json_line()
        assert RegistryRecord.from_json_line(line) == record
        assert record.to_json_line() == line  # 字节级可重复
        assert ": " not in line and ", " not in line  # 无空白分隔
        assert line == json.dumps(json.loads(line), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        # 签名载荷不含 signature 字段
        assert "signature" not in record.payload_dict()
        assert len(bytes.fromhex(record.signature)) == 64

    @pytest.mark.parametrize(
        "overrides, code, path",
        [
            (dict(revalidate_period_days=0.0), "value_out_of_range", "revalidate_period_days"),
            (dict(revalidate_period_days=-30.0), "value_out_of_range", "revalidate_period_days"),
            (dict(record_version=0), "value_out_of_range", "record_version"),
            (dict(last_verified="2026-06-01T10:00:00"), "timestamp_missing_timezone", "last_verified"),
            (dict(last_verified="not-a-date"), "format_error", "last_verified"),
            (dict(installed_on="2026/01/15"), "format_error", "installed_on"),
            (dict(target_id="   "), "format_error", "target_id"),
            (dict(target_id=42), "type_error", "target_id"),
            (dict(signature="deadbeef"), "signature_format_error", "signature"),
        ],
    )
    def test_rejects_invalid_fields(self, overrides, code, path):
        """负例：非法字段显式抛错（fail-closed，无默认值填充）。"""
        with pytest.raises(RegistryError) as excinfo:
            make_record(**overrides)
        assert excinfo.value.code == code
        assert excinfo.value.path == path

    def test_rejects_unknown_and_missing_dict_keys(self):
        """负例：from_dict 缺键 / 多键均拒绝。"""
        good = make_record().to_dict()
        missing = {k: v for k, v in good.items() if k != "frame_ref"}
        with pytest.raises(RegistryError) as excinfo:
            RegistryRecord.from_dict(missing)
        assert excinfo.value.code == "missing_field"
        extra = dict(good, extra_field="x")
        with pytest.raises(RegistryError) as excinfo:
            RegistryRecord.from_dict(extra)
        assert excinfo.value.code == "unknown_field"


# ===================== R-2 append-only 存储 =====================


class TestR2AppendOnly:
    def test_append_then_replay_chain_consistent(self, store: RegistryStore):
        """正例：多条事件追加后重放，链完整且幂等。"""
        first = store.append(KIND_REGISTER, signed_record().to_dict())
        second = store.append(KIND_REGISTER, signed_record(target_id="ORG-0001:00000002").to_dict())
        store.append(
            KIND_RETIRE,
            Tombstone("ORG-0001:00000002", "2026-07-01T00:00:00+08:00", "physical damage").to_dict(),
        )
        events, head = store.replay()
        assert len(events) == 3
        assert head == second.entry_hash or head == events[-1].entry_hash
        assert head == events[-1].entry_hash
        assert first.prev_hash == GENESIS_HASH
        # 幂等：再次重放结果一致
        events2, head2 = store.replay()
        assert events2 == events and head2 == head

    def test_no_delete_or_rewrite_api(self):
        """负例（结构）：实现层不给物理删除 / 原地改写接口。"""
        forbidden = {"delete", "remove", "pop", "update", "overwrite", "erase", "rewrite", "truncate", "write", "clear"}
        exposed = {name for name in dir(RegistryStore) if not name.startswith("_")}
        assert exposed & forbidden == set(), f"store must not expose mutation API, found {exposed & forbidden}"
        # 唯一公开写方法是 append；其余公开成员只有只读查询（私有 helper / dunder 除外）
        read_only = {"path", "append", "replay", "latest_records", "tombstones"}
        methods = {
            name
            for name, member in vars(RegistryStore).items()
            if not name.startswith("_") and callable(member) and not isinstance(member, property)
        }
        assert methods - read_only == set(), f"unexpected store methods: {methods - read_only}"

    def test_rewritten_line_detected_as_tampered(self, store: RegistryStore, tmp_path: Path):
        """负例：原地改写历史行（改 payload 不改 entry_hash）→ payload_tampered。"""
        store.append(KIND_REGISTER, signed_record().to_dict())
        store.append(KIND_REGISTER, signed_record(target_id="ORG-0001:00000002").to_dict())
        store.append(KIND_REGISTER, signed_record(target_id="ORG-0001:00000003").to_dict())
        lines = store.path.read_text(encoding="utf-8").splitlines()
        tampered = json.loads(lines[1])
        tampered["payload"]["object_ref"] = "attacker:object"  # 原地改写中间行
        lines[1] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
        _write_lines(store.path, lines)
        with pytest.raises(RegistryError) as excinfo:
            store.replay()
        assert excinfo.value.code == "payload_tampered"

    def test_deleted_line_breaks_chain(self, store: RegistryStore):
        """负例：物理删除中间行 → chain_broken。"""
        store.append(KIND_REGISTER, signed_record().to_dict())
        store.append(KIND_REGISTER, signed_record(target_id="ORG-0001:00000002").to_dict())
        store.append(KIND_REGISTER, signed_record(target_id="ORG-0001:00000003").to_dict())
        lines = store.path.read_text(encoding="utf-8").splitlines()
        del lines[1]  # 删除中间行
        _write_lines(store.path, lines)
        with pytest.raises(RegistryError) as excinfo:
            store.replay()
        assert excinfo.value.code == "chain_broken"

    def test_unsigned_register_refused_at_append(self, store: RegistryStore):
        """负例：无签名记录不得入库（实现层收紧，见 registry-notes.md）。"""
        with pytest.raises(RegistryError) as excinfo:
            store.append(KIND_REGISTER, make_record().to_dict())
        assert excinfo.value.code == "missing_signature"

    def test_version_regression_refused(self, store: RegistryStore):
        """负例：同 ID 新版本号不递增 → version_regression。"""
        store.append(KIND_REGISTER, signed_record(record_version=2).to_dict())
        with pytest.raises(RegistryError) as excinfo:
            store.append(KIND_REGISTER, signed_record(record_version=2).to_dict())
        assert excinfo.value.code == "version_regression"

    def test_supersede_appends_new_version(self, store: RegistryStore):
        """正例：同 ID 版本递增的追加（append-only 更新 = 新事件，不改历史）。"""
        store.append(KIND_REGISTER, signed_record(record_version=1).to_dict())
        store.append(KIND_REGISTER, signed_record(record_version=2).to_dict())
        events, _ = store.replay()
        assert len(events) == 2  # 历史保留
        assert store.latest_records()[BASE["target_id"]].record_version == 2


# ===================== R-3 墓碑 =====================


class TestR3Tombstone:
    def test_retire_creates_terminal_tombstone(self, store: RegistryStore):
        """正例：报废进入墓碑终态；该 ID 不再有"最新记录"。"""
        store.append(KIND_REGISTER, signed_record().to_dict())
        store.append(
            KIND_RETIRE,
            Tombstone(BASE["target_id"], "2026-07-01T00:00:00+08:00", "physical damage").to_dict(),
        )
        assert BASE["target_id"] in store.tombstones()
        assert BASE["target_id"] not in store.latest_records()
        # 终态：再次报废拒绝
        with pytest.raises(RegistryError) as excinfo:
            store.append(
                KIND_RETIRE,
                Tombstone(BASE["target_id"], "2026-07-02T00:00:00+08:00", "again").to_dict(),
            )
        assert excinfo.value.code == "already_tombstoned"

    def test_tombstoned_id_reuse_refused(self, store: RegistryStore):
        """负例（Q12）：墓碑 ID 复用登记 → tombstone_reuse；换新版本号同样拒绝。"""
        store.append(KIND_REGISTER, signed_record().to_dict())
        store.append(
            KIND_RETIRE,
            Tombstone(BASE["target_id"], "2026-07-01T00:00:00+08:00", "physical damage").to_dict(),
        )
        for version in (1, 2, 99):
            with pytest.raises(RegistryError) as excinfo:
                store.append(KIND_REGISTER, signed_record(record_version=version).to_dict())
            assert excinfo.value.code == "tombstone_reuse"

    def test_retire_unknown_id_refused(self, store: RegistryStore):
        """负例：报废未注册 ID → unknown_id。"""
        with pytest.raises(RegistryError) as excinfo:
            store.append(
                KIND_RETIRE,
                Tombstone("GHOST:0001", "2026-07-01T00:00:00+08:00", "never existed").to_dict(),
            )
        assert excinfo.value.code == "unknown_id"

    def test_bind_tombstoned_id_refused(self, store: RegistryStore):
        """负例：墓碑 ID 语义绑定拒绝。"""
        store.append(KIND_REGISTER, signed_record().to_dict())
        store.append(
            KIND_RETIRE,
            Tombstone(BASE["target_id"], "2026-07-01T00:00:00+08:00", "physical damage").to_dict(),
        )
        with pytest.raises(RegistryError) as excinfo:
            bind_semantics(BASE["target_id"], store.path, PUB, now=datetime(2026, 6, 10, tzinfo=TZ))
        assert excinfo.value.code == "tombstoned_id"


# ===================== R-4 离线快照 =====================


class TestR4Snapshot:
    def _build_signed_snapshot_file(self, store: RegistryStore, tmp_path: Path) -> Path:
        store.append(KIND_REGISTER, signed_record().to_dict())
        store.append(KIND_REGISTER, signed_record(target_id="ORG-0001:00000002").to_dict())
        store.append(
            KIND_RETIRE,
            Tombstone("ORG-0001:00000002", "2026-07-01T00:00:00+08:00", "physical damage").to_dict(),
        )
        events, head = store.replay()
        snapshot = build_snapshot(events, snapshot_version=1, created_at="2026-07-02T00:00:00+08:00")
        path = tmp_path / "snapshot.json"
        write_snapshot(path, sign_snapshot(snapshot, KEY))
        return path

    def test_offline_verification_succeeds(self, store: RegistryStore, tmp_path: Path):
        """正例：无网络环境只凭快照文件 + 公钥独立校验通过（含记录级签名）。"""
        path = self._build_signed_snapshot_file(store, tmp_path)
        verified = verify_offline(path, PUB)
        assert [rec.target_id for rec in verified.records] == [BASE["target_id"]]
        assert [ts.target_id for ts in verified.tombstones] == ["ORG-0001:00000002"]
        assert verified.head_hash == store.replay()[1]

    def test_tampered_snapshot_rejected(self, store: RegistryStore, tmp_path: Path):
        """负例：篡改快照内容（改记录周期）→ 快照级验签失败。"""
        path = self._build_signed_snapshot_file(store, tmp_path)
        obj = json.loads(path.read_text(encoding="utf-8"))
        obj["records"][0]["revalidate_period_days"] = 9999.0  # 投毒：拉长周期规避 R-6
        path.write_text(json.dumps(obj, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        with pytest.raises(RegistryError) as excinfo:
            verify_offline(path, PUB)
        assert excinfo.value.code == "signature_invalid"

    def test_tampered_record_inside_snapshot_rejected(self, store: RegistryStore, tmp_path: Path):
        """负例：篡改单条记录但保留快照签名 → 记录级验签失败（两级签名独立生效）。"""
        path = self._build_signed_snapshot_file(store, tmp_path)
        obj = json.loads(path.read_text(encoding="utf-8"))
        obj["records"][0]["object_ref"] = "attacker:object"
        path.write_text(json.dumps(obj, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        with pytest.raises(RegistryError) as excinfo:
            verify_offline(path, PUB)
        assert excinfo.value.code in {"signature_invalid", "missing_signature"}

    def test_broken_and_unsigned_snapshots_rejected(self, tmp_path: Path):
        """负例：结构损坏 → snapshot_invalid；未签名快照 → missing_signature。"""
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(RegistryError) as excinfo:
            verify_offline(bad, PUB)
        assert excinfo.value.code == "snapshot_invalid"

        snapshot = build_snapshot(
            [], snapshot_version=1, created_at="2026-07-02T00:00:00+08:00"
        )  # 空事件流 → GENESIS
        with pytest.raises(RegistryError) as excinfo:
            verify_snapshot(snapshot, PUB)
        assert excinfo.value.code == "missing_signature"


# ===================== R-5 语义绑定验签 =====================


class TestR5BindSemantics:
    def test_bind_signed_record_succeeds(self, store: RegistryStore):
        """正例：合法签名记录绑定成功，返回该 ID 最新版本。"""
        store.append(KIND_REGISTER, signed_record(record_version=1).to_dict())
        store.append(KIND_REGISTER, signed_record(record_version=2).to_dict())
        bound = bind_semantics(BASE["target_id"], store.path, PUB, now=datetime(2026, 6, 10, tzinfo=TZ))
        assert bound.record_version == 2

    def test_tampered_record_fails_signature(self):
        """负例：篡改已签名记录字段 → 验签失败（防伪第一级）。"""
        record = signed_record()
        tampered = dataclasses.replace(record, object_ref="attacker:object")
        with pytest.raises(RegistryError) as excinfo:
            verify_signature(tampered, PUB)
        assert excinfo.value.code == "signature_invalid"

    def test_unsigned_record_binding_refused(self, tmp_path: Path):
        """负例：库中查无签名记录（D2 注入的无签名事件，链自洽）→ 拒绝绑定。"""
        record = make_record()  # signature=None，绕过 append 直接落盘（模拟投毒者）
        payload = record.to_dict()
        event = StoreEvent(
            KIND_REGISTER, payload, GENESIS_HASH, compute_entry_hash(GENESIS_HASH, KIND_REGISTER, payload)
        )
        path = tmp_path / "poisoned.jsonl"
        _write_lines(path, [event.to_json_line()])
        with pytest.raises(RegistryError) as excinfo:
            bind_semantics(BASE["target_id"], path, PUB, now=datetime(2026, 6, 10, tzinfo=TZ))
        assert excinfo.value.code == "missing_signature"

    def test_unknown_id_binding_refused(self, store: RegistryStore):
        """负例：查无记录的 ID → 拒绝语义绑定（R-5 文本行为）。"""
        with pytest.raises(RegistryError) as excinfo:
            bind_semantics("NOBODY:0001", store.path, PUB, now=datetime(2026, 6, 10, tzinfo=TZ))
        assert excinfo.value.code == "no_signed_record"

    def test_wrong_authority_key_rejected(self, store: RegistryStore):
        """负例：非签发权威的公钥验签 → signature_invalid（T-3/T-4a 边界）。"""
        store.append(KIND_REGISTER, signed_record().to_dict())
        with pytest.raises(RegistryError) as excinfo:
            bind_semantics(BASE["target_id"], store.path, WRONG_KEY.public_key(), now=datetime(2026, 6, 10, tzinfo=TZ))
        assert excinfo.value.code == "signature_invalid"

    def test_binding_requires_chain_integrity(self, store: RegistryStore):
        """负例：存储链被篡改 → 绑定在链校验一步即拒绝。"""
        store.append(KIND_REGISTER, signed_record().to_dict())
        lines = store.path.read_text(encoding="utf-8").splitlines()
        lines[0] = lines[0].replace('"robot:r1"', '"attacker:object"')
        _write_lines(store.path, lines)
        with pytest.raises(RegistryError) as excinfo:
            bind_semantics(BASE["target_id"], store.path, PUB, now=datetime(2026, 6, 10, tzinfo=TZ))
        assert excinfo.value.code in {"payload_tampered", "chain_broken"}


# ===================== R-6 复验周期两级处置 =====================


class TestR6Expiry:
    """按 PROP-20261123-CTP-TBDG-0.2 §G5 提案实现（待 WG-RES 追认）；周期全部显式传参。"""

    @pytest.mark.parametrize(
        "now, expected",
        [
            (datetime(2026, 6, 11, 10, 0, tzinfo=TZ), ExpiryStatus.OK),                # age 10d < 30d
            (datetime(2026, 7, 1, 10, 0, tzinfo=TZ), ExpiryStatus.PENDING_REVALIDATION),  # age 30d，边界 >= 计入超期
            (datetime(2026, 7, 20, 10, 0, tzinfo=TZ), ExpiryStatus.PENDING_REVALIDATION),  # 30d <= age < 60d
            (datetime(2026, 7, 31, 10, 0, tzinfo=TZ), ExpiryStatus.QUARANTINE),        # age 60d = 2x period
            (datetime(2026, 9, 1, 10, 0, tzinfo=TZ), ExpiryStatus.QUARANTINE),         # age >> 2x period
        ],
    )
    def test_two_level_classification(self, now, expected):
        """正例：last_verified + period → ok / 待复验 / quarantine（G5 两级）。"""
        record = signed_record()  # period=30 天（测试参数）
        assert classify_expiry(record, now) is expected

    def test_period_comes_from_record_not_constant(self):
        """正例：周期换值结果随之变化——门槛只来自记录字段，无隐藏常量。"""
        record = signed_record(revalidate_period_days=7.0)  # last_verified=2026-06-01
        assert classify_expiry(record, datetime(2026, 6, 10, 10, 0, tzinfo=TZ)) is ExpiryStatus.PENDING_REVALIDATION  # age 9d ∈ [7,14)
        assert classify_expiry(record, datetime(2026, 6, 16, 10, 0, tzinfo=TZ)) is ExpiryStatus.QUARANTINE  # age 15d ≥ 2×7d

    def test_no_hardcoded_period_defaults(self):
        """结构负例：规范层零硬编码门槛——revalidate_period_days 与 now 均无默认值。"""
        fields = {f.name: f for f in dataclasses.fields(RegistryRecord)}
        assert fields["revalidate_period_days"].default is dataclasses.MISSING
        assert fields["last_verified"].default is dataclasses.MISSING
        sig = inspect.signature(classify_expiry)
        assert sig.parameters["now"].default is inspect.Signature.empty
        assert inspect.signature(bind_semantics).parameters["now"].default is inspect.Signature.empty
        # G5 倍数是提案结构常量（2x），非实现发明；断言其取值与来源标注并存
        assert G5_QUARANTINE_PERIODS == 2.0

    def test_quarantine_blocks_binding_with_g5_note(self, store: RegistryStore):
        """负例：2x 超期 → quarantine 拒绝语义绑定；detail 标注按 G5 提案、待 WG-RES 追认。"""
        store.append(KIND_REGISTER, signed_record().to_dict())  # last_verified=2026-06-01, period=30d
        with pytest.raises(RegistryError) as excinfo:
            bind_semantics(BASE["target_id"], store.path, PUB, now=datetime(2026, 8, 1, 10, 0, tzinfo=TZ))
        assert excinfo.value.code == "quarantined_record"
        assert "PROP-20261123-CTP-TBDG-0.2" in excinfo.value.detail
        assert "WG-RES" in excinfo.value.detail

    def test_pending_revalidation_does_not_block_binding(self, store: RegistryStore):
        """正例（G5 一级）：待复验可绑定——"可用但禁入高精度"是读码器侧 C-5 标记，不在绑定拦截。"""
        store.append(KIND_REGISTER, signed_record().to_dict())
        bound = bind_semantics(BASE["target_id"], store.path, PUB, now=datetime(2026, 7, 15, 10, 0, tzinfo=TZ))
        assert bound.target_id == BASE["target_id"]
        assert classify_expiry(bound, datetime(2026, 7, 15, 10, 0, tzinfo=TZ)) is ExpiryStatus.PENDING_REVALIDATION

    def test_naive_now_rejected(self):
        """负例：now 无时区 → 显式拒绝（无本地时区歧义）。"""
        with pytest.raises(RegistryError) as excinfo:
            classify_expiry(signed_record(), datetime(2026, 7, 1, 10, 0))
        assert excinfo.value.code == "timestamp_missing_timezone"
