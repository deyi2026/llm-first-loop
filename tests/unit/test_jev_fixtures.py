"""EVO-20261015 (P1a): 冻结盲评集与零外发守卫（DESIGN §11 P1a 验收面）。"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
import sys

from llm_loop.knowledge.jev.wire import (
    QuestionSpec,
    build_request,
    normalize_response,
)

# conftest.isolated_data_dir 会 monkeypatch.chdir(tmp_path)——相对路径不可用，锚定本文件。
_REPO = pathlib.Path(__file__).resolve().parents[2]
ROOT = _REPO / "tests/fixtures/jev/blind_eval_v1"
JEV_PKG = _REPO / "src/llm_loop/knowledge/jev"

_NETWORK_IMPORT = re.compile(
    r"^\s*(import|from)\s+(httpx|requests|urllib|socket|ssl|aiohttp|ftplib"
    r"|telnetlib|websocket|httpx_client|http)"
    r"\b|^\s*from\s+http\s+import\s+client", re.M,
)


class TestFrozenManifest:
    def test_manifest_hashes_match_every_file(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        entries = [*manifest["cases"], *manifest["wire_examples"], manifest["labels"]]
        assert entries, "empty manifest"
        for entry in entries:
            path = ROOT / entry["file"]
            digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == entry["sha256"], f"fixture drifted: {entry['file']}"

    def test_blind_labels_not_in_judge_visible_files(self):
        for case_file in sorted((ROOT / "cases").glob("*.json")):
            payload = json.loads(case_file.read_text(encoding="utf-8"))
            flat = json.dumps(payload, ensure_ascii=False)
            for forbidden in ("\"actual\"", "\"label_state\"", "\"labels\"", "\"evidence\":"):
                assert forbidden not in flat, (
                    f"{case_file.name} leaks label-ish field {forbidden}"
                )
            for key in payload.get("allowlist", []):
                assert key not in ("actual", "label", "labels", "label_state")

    def test_labels_file_exists_but_is_not_judge_input(self):
        labels = json.loads((ROOT / "labels" / "labels.json").read_text(encoding="utf-8"))
        cases = {c["file"] for c in json.loads(
            (ROOT / "manifest.json").read_text(encoding="utf-8"))["cases"]}
        assert labels["labels"], "labels empty"
        assert all("labels" not in f for f in cases)


class TestWireExamplesValidateAsExpected:
    """wire_examples 既是契约文档也是回归样本：按预期分类通过/失败。"""

    def _case_request(self):
        q = QuestionSpec(
            name="premise_linux", type="choice", instructions="判断",
            criteria={"yes": "y", "no": "n", "unknown": "u"},
        )
        return build_request(
            model="m",
            state={"subject_ref": "experience:x", "subject_hash": "sha256:x"},
            questions={"premise_linux": q},
        )

    def _normalize(self, name: str):
        raw = json.loads(
            (ROOT / "wire_examples" / name).read_text(encoding="utf-8"))
        return normalize_response(
            request=self._case_request(), raw=raw, transport_status="ok")

    def test_valid_minimal(self):
        resp = self._normalize("valid_minimal.json")
        assert resp.summary()["valid"] == 1
        assert resp.usage.status == "valid"
        assert resp.resolved_model == "jev-1.13.0-resolved"

    def test_invalid_prob_sum(self):
        resp = self._normalize("invalid_prob_sum.json")
        assert resp.summary()["contract_invalid"] == 1

    def test_invalid_confidence_range(self):
        assert self._normalize("invalid_confidence_range.json").summary()["contract_invalid"] == 1

    def test_invalid_choice_not_in_options(self):
        resp = self._normalize("invalid_choice_not_in_options.json")
        assert resp.summary()["contract_invalid"] == 1

    def test_missing_question(self):
        assert self._normalize("missing_question.json").summary()["missing"] == 1

    def test_usage_missing_is_unknown(self):
        resp = self._normalize("usage_missing.json")
        assert resp.usage.status == "unknown"
        assert resp.usage.total_tokens is None

    def test_noul_no_confidence_sample(self):
        # P2-1：第 8 个 wire 样本此前未被任何测试消费。
        q = QuestionSpec(name="unverified_platform_caveat", type="noul",
                         instructions="提取", criteria={})
        raw = json.loads((ROOT / "wire_examples" / "noul_no_confidence.json")
                         .read_text(encoding="utf-8"))
        resp = normalize_response(
            request=build_request(model="m", state={"subject_ref": "x"},
                                  questions={"unverified_platform_caveat": q}),
            raw=raw, transport_status="ok")
        assert resp.summary()["valid"] == 1
        assert resp.answers["unverified_platform_caveat"].confidence is None

    def test_resolved_model_missing(self):
        resp = self._normalize("resolved_model_missing.json")
        assert resp.resolved_model is None
        assert "resolved_model_missing" in resp.batch_invalid_reasons


class TestZeroOutboundGuards:
    def test_network_import_regex_catches_http_client_spellings(self):
        # 窄复审 NF-2：两种规范拼写都必须被 tripwire 捕获。
        assert _NETWORK_IMPORT.search("import http.client")
        assert _NETWORK_IMPORT.search("from http.client import HTTPConnection")
        assert _NETWORK_IMPORT.search("import httpx")
        assert _NETWORK_IMPORT.search("from http import client")
        assert not _NETWORK_IMPORT.search("import json")

    def test_jev_package_has_no_network_imports(self):
        offenders = []
        for py in sorted(JEV_PKG.glob("*.py")):
            if _NETWORK_IMPORT.search(py.read_text(encoding="utf-8")):
                offenders.append(py.name)
        assert not offenders, f"jev 包出现网络 import（P1a 禁止）: {offenders}"

    def test_no_live_wiring_of_jev_shadow_event(self):
        # §6.3/§11：P1a 不接入 live 路径——src 内 knowledge/jev 之外不得引用本事件/runner。
        result = subprocess.run(
            [sys.executable, "-c", (
                "import pathlib,sys;"
                "hits=[];"
                "[hits.append(str(p)) for p in pathlib.Path('src/llm_loop').rglob('*.py')"
                " if 'knowledge/jev' not in p.as_posix()"
                " and any(m in p.read_text(encoding='utf-8')"
                " for m in ('jev_shadow', 'knowledge.jev', 'JevShadowRunner'))];"
                "print('\\n'.join(hits))"
            )],
            capture_output=True, text=True, cwd=str(_REPO),
        )
        assert result.returncode == 0, result.stderr
        assert not result.stdout.strip(), (
            f"live 路径引用 jev shadow（P1a 未授权接线）: {result.stdout.strip()}"
        )

    def test_default_policy_keeps_off_semantics(self):
        # P1a 不新增启用开关：包内唯一入口 runner 需显式注入 transport 才能工作，
        # 不存在默认构造出“会外发”对象的路径。
        import inspect

        from llm_loop.knowledge.jev import JevShadowRunner, MockJevTransport
        sig = inspect.signature(JevShadowRunner.__init__)
        assert sig.parameters["transport"].default is inspect.Parameter.empty
        assert MockJevTransport.__module__.startswith("llm_loop.knowledge.jev")
