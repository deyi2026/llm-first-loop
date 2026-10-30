"""Mechanical evidence collector: every judgement class must actually block.

Proposal-only contract under test too: the collector must leave the methods dir
byte-identical, must refuse outputs inside the methods dir, and must not import
or construct the store. Judgement pins (R3 事实轴): URL 200 never fails,
transient network trouble never fails, a single 404 is never ready_to_land,
two 404s closer than the min gap are not double-sampled, an existing path is
never marked missing, and a missing body mention is never convicted on its own.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "qualification" / "method_mechanical_evidence.py"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "qualification"))

import method_mechanical_evidence as mech  # noqa: E402

# --------------------------------------------------------------------- fixtures


def _card(name: str, *, status: str = "candidate", freshness: str = "",
          evidence: str = "", body: str = "") -> str:
    fm = [
        "---",
        f"method_id: {name}-000000000000",
        f"name: {name}",
        "description: fixture card",
        f"status: {status}",
        "source_model: test",
    ]
    if freshness:
        fm.append(f"freshness_refs: {freshness}")
    if evidence:
        fm.append(f"evidence_refs: {evidence}")
    fm += ["---", "", body or "## Trigger\nfixture", ""]
    return "\n".join(fm)


def _make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """(methods_dir, repo_root) — repo_root carries the files cards anchor on."""
    repo_root = tmp_path / "repo"
    methods_dir = repo_root / "data" / "methods"
    (repo_root / "tests" / "fixtures").mkdir(parents=True)
    (repo_root / "tests" / "fixtures" / "exists.md").write_text("anchor", encoding="utf-8")
    (repo_root / "src" / "llm_loop" / "tools").mkdir(parents=True)
    (repo_root / "src" / "llm_loop" / "tools" / "registry.py").write_text(
        "_COMPACT_TOOL_DESCRIPTIONS = {\n"
        '    "read_file": "read",\n    "execute_command": "run",\n}\n',
        encoding="utf-8",
    )
    cards = {
        "card-anchor-a": _card(
            "card-anchor-a",
            freshness="tests/fixtures/exists.md",
            body=(
                "## Short path\n- 读 `docs/gone-report.md` 再用 `read_file` 取证\n"
                "- 参考 https://live.vendor.io/notes\n"
            ),
        ),
        "card-dead-url-b": _card(
            "card-dead-url-b",
            body="## Trigger\n依赖 https://dead.vendor.io/old-post 的清单\n",
        ),
        "card-hold-c": _card("card-hold-c", status="hold"),
    }
    for slug, text in cards.items():
        # house convention: card dir name == full method_id (slug + hash suffix)
        card_id = f"{slug}-000000000000"
        (methods_dir / card_id).mkdir(parents=True)
        (methods_dir / card_id / "METHOD.md").write_text(text, encoding="utf-8")
    ledger = [
        {"method_ref": "method:card-anchor-a-000000000000", "decision": "applied",
         "ts": "2026-10-01T00:00:00+00:00"},
        {"method_ref": "method:card-anchor-a-000000000000", "decision": "rejected",
         "ts": "2026-10-02T00:00:00+00:00"},
        {"method_ref": "method:card-dead-url-b-000000000000", "decision": "applied",
         "ts": "2026-10-03T00:00:00+00:00"},
        {"method_ref": "method:card-hold-c-000000000000", "decision": "applied",
         "ts": "2026-10-04T00:00:00+00:00"},
    ]
    (methods_dir / "usage.jsonl").write_text(
        "\n".join(json.dumps(row) for row in ledger) + "\n", encoding="utf-8"
    )
    return methods_dir, repo_root


def _url_result(code: int | None, *, transient: bool = False) -> dict:
    return {
        "command": "curl ... (fixture)",
        "http_code": code,
        "exit_code": 0 if code is not None else 7,
        "output_excerpt": f"http_code={'-' if code is None else code}",
        "transient": transient or code is None,
        "ts": mech._now_iso(),
    }


def _collect(tmp_path: Path, methods_dir: Path, repo_root: Path, *, url_code_map: dict[str, int | None],
             url_phase: str = "sample1", state: dict | None = None):
    def url_checker(url: str, timeout_s: int) -> dict:
        return _url_result(url_code_map.get(url))

    out_json = tmp_path / "out" / "manifest.json"
    state_path = tmp_path / "out" / "samples.json"
    if state is not None:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), encoding="utf-8")
    payload = mech.run_collect(
        methods_dir,
        out_json=out_json,
        out_md=tmp_path / "out" / "manifest.md",
        state_path=state_path,
        url_phase=url_phase,
        repo_root=repo_root,
        url_checker=url_checker,
    )
    return payload, state_path


def _findings(payload: dict, check_type: str) -> list[dict]:
    return [f for c in payload["cards"] for f in c["findings"] if f["check_type"] == check_type]


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


# ------------------------------------------------------------ URL judgements


def test_url_200_never_fails() -> None:
    verdict, _ = mech.judge_url([{"http_code": 200, "ts": "2026-10-30T00:00:00+00:00"}])
    assert verdict == "pass"


def test_transient_network_error_never_fails() -> None:
    for samples in (
        [{"http_code": None, "transient": True, "ts": "2026-10-30T00:00:00+00:00"}],
        [{"http_code": 503, "ts": "2026-10-30T00:00:00+00:00"},
         {"http_code": 403, "ts": "2026-10-30T00:20:00+00:00"}],
    ):
        verdict, _ = mech.judge_url(samples)
        assert verdict == "no_verdict"


def test_single_404_is_pending_not_ready() -> None:
    verdict, _ = mech.judge_url([{"http_code": 404, "ts": "2026-10-30T00:00:00+00:00"}])
    assert verdict == "pending_sample2"


def test_double_404_with_gap_fails() -> None:
    verdict, note = mech.judge_url([
        {"http_code": 404, "ts": "2026-10-30T00:00:00+00:00"},
        {"http_code": 404, "ts": "2026-10-30T00:15:00+00:00"},
    ])
    assert verdict == "fail"
    assert "≥" in note


def test_double_404_too_close_is_not_double_sampled() -> None:
    verdict, _ = mech.judge_url([
        {"http_code": 404, "ts": "2026-10-30T00:00:00+00:00"},
        {"http_code": 404, "ts": "2026-10-30T00:01:00+00:00"},
    ])
    assert verdict == "pending_sample2"


def test_integration_url_200_and_transient_do_not_fail(tmp_path: Path) -> None:
    methods_dir, repo_root = _make_workspace(tmp_path)
    payload, _ = _collect(
        tmp_path, methods_dir, repo_root,
        url_code_map={"https://live.vendor.io/notes": 200,
                      "https://dead.vendor.io/old-post": None},
    )
    url = {f["claim"]["text"]: f for f in _findings(payload, "url")}
    live = next(f for key, f in url.items() if "live.vendor" in key)
    dead_transient = next(f for key, f in url.items() if "dead.vendor" in key)
    assert live["verdict"] == "pass" and live["ready_to_land"] is False
    assert dead_transient["verdict"] == "no_verdict" and dead_transient["ready_to_land"] is False


def test_integration_sample1_404_pending_sample2_not_ready(tmp_path: Path) -> None:
    methods_dir, repo_root = _make_workspace(tmp_path)
    payload, state_path = _collect(
        tmp_path, methods_dir, repo_root,
        url_code_map={"https://live.vendor.io/notes": 200,
                      "https://dead.vendor.io/old-post": 404},
    )
    dead = [f for f in _findings(payload, "url") if "dead.vendor" in f["claim"]["text"]][0]
    assert dead["verdict"] == "pending_sample2"
    assert dead["ready_to_land"] is False
    assert payload["url_sampling"]["pending_sample2"] == 1
    # state remembers sample1 for the later sample2 run
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["url_samples"]["https://dead.vendor.io/old-post"]["samples"][0]["http_code"] == 404


def test_integration_sample2_gated_by_gap(tmp_path: Path) -> None:
    methods_dir, repo_root = _make_workspace(tmp_path)
    url = "https://dead.vendor.io/old-post"
    early = (datetime.now(UTC) - timedelta(seconds=100)).isoformat()
    state = {"url_samples": {url: {"samples": [{"http_code": 404, "ts": early}]}}}
    payload, state_path = _collect(
        tmp_path, methods_dir, repo_root, url_code_map={url: 404},
        url_phase="sample2", state=state,
    )
    dead = [f for f in _findings(payload, "url") if url in f["claim"]["text"]][0]
    assert dead["verdict"] == "pending_sample2"  # gap not met -> no second sample
    assert dead["ready_to_land"] is False
    samples = json.loads(state_path.read_text(encoding="utf-8"))["url_samples"][url]["samples"]
    assert len(samples) == 1

    late = (datetime.now(UTC) - timedelta(seconds=700)).isoformat()
    state = {"url_samples": {url: {"samples": [{"http_code": 404, "ts": late}]}}}
    payload, _ = _collect(
        tmp_path, methods_dir, repo_root, url_code_map={url: 404},
        url_phase="sample2", state=state,
    )
    dead = [f for f in _findings(payload, "url") if url in f["claim"]["text"]][0]
    assert dead["verdict"] == "fail"
    assert dead["ready_to_land"] is True


# ---------------------------------------------------------- path judgements


def test_existing_path_is_never_marked_missing(tmp_path: Path) -> None:
    methods_dir, repo_root = _make_workspace(tmp_path)
    payload, _ = _collect(tmp_path, methods_dir, repo_root, url_code_map={})
    anchor = [
        f for f in _findings(payload, "local_path")
        if f["claim"]["location"] == "frontmatter.freshness_refs"
    ][0]
    assert anchor["verdict"] == "pass"
    assert anchor["ready_to_land"] is False
    assert anchor["evidence"]["exit_code"] == 0


def test_missing_anchor_fails_but_body_mention_stays_manual(tmp_path: Path) -> None:
    methods_dir, repo_root = _make_workspace(tmp_path)
    # rewrite the anchor card's freshness to a gone path
    card_path = methods_dir / "card-anchor-a-000000000000" / "METHOD.md"
    card_path.write_text(
        card_path.read_text(encoding="utf-8").replace(
            "tests/fixtures/exists.md", "tests/fixtures/gone.md"
        ),
        encoding="utf-8",
    )
    payload, _ = _collect(tmp_path, methods_dir, repo_root, url_code_map={})
    paths = _findings(payload, "local_path")
    anchor = [f for f in paths if f["claim"]["location"] == "frontmatter.freshness_refs"][0]
    mention = [f for f in paths if f["claim"]["location"] == "body"][0]
    assert anchor["verdict"] == "fail" and anchor["ready_to_land"] is True
    assert mention["verdict"] == "manual_review" and mention["ready_to_land"] is False
    assert "reopen" in anchor["rollback"]["undo"][0]


# --------------------------------------------------------- tool judgements


def test_tool_in_catalog_passes_missing_stays_manual(tmp_path: Path) -> None:
    methods_dir, repo_root = _make_workspace(tmp_path)
    card_path = methods_dir / "card-anchor-a-000000000000" / "METHOD.md"
    card_path.write_text(
        card_path.read_text(encoding="utf-8").replace("`read_file`", "`read_file` 与 `zz_not_a_tool`"),
        encoding="utf-8",
    )
    payload, _ = _collect(tmp_path, methods_dir, repo_root, url_code_map={})
    tools = {f["claim"]["text"]: f for f in _findings(payload, "tool_existence")}
    known = next(f for key, f in tools.items() if "read_file" in key)
    unknown = next(f for key, f in tools.items() if "zz_not_a_tool" in key)
    assert known["verdict"] == "pass"
    assert unknown["verdict"] == "manual_review" and unknown["ready_to_land"] is False


def test_registry_catalog_reads_real_registry() -> None:
    names, source = mech.registry_tool_names(REPO_ROOT)
    assert names is not None
    assert {"read_file", "search_records", "execute_command"} <= names
    assert "registry.py" in source
    # builtin module stems are the second static source (edit_file.py -> edit_file)
    assert "edit_file" in names


# ------------------------------------------------- proposal-only / no-write


def test_methods_dir_is_byte_identical_after_collect(tmp_path: Path) -> None:
    methods_dir, repo_root = _make_workspace(tmp_path)
    before = _tree_hash(methods_dir)
    _collect(tmp_path, methods_dir, repo_root, url_code_map={})
    assert _tree_hash(methods_dir) == before


def test_output_inside_methods_dir_is_refused(tmp_path: Path) -> None:
    methods_dir, repo_root = _make_workspace(tmp_path)
    import pytest

    with pytest.raises(SystemExit):
        mech.run_collect(
            methods_dir,
            out_json=methods_dir / "manifest.json",
            out_md=tmp_path / "out.md",
            repo_root=repo_root,
            url_checker=lambda url, t: _url_result(None),
        )
    assert not (methods_dir / "manifest.json").exists()


def test_script_never_imports_or_builds_the_store() -> None:
    # AST-level guarantee (docstrings may mention the store by name; code may not)
    import ast as ast_mod

    tree = ast_mod.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast_mod.walk(tree):
        if isinstance(node, ast_mod.Import):
            assert all(not alias.name.startswith("llm_loop.methods") for alias in node.names)
        if isinstance(node, ast_mod.ImportFrom):
            assert not (node.module or "").startswith("llm_loop.methods")
        if isinstance(node, ast_mod.Name):
            assert node.id != "MethodStore"


def test_manifest_carries_required_fields(tmp_path: Path) -> None:
    methods_dir, repo_root = _make_workspace(tmp_path)
    payload, _ = _collect(tmp_path, methods_dir, repo_root, url_code_map={})
    assert payload["proposal_only"] is True
    every = [f for c in payload["cards"] for f in c["findings"]]
    assert every
    for finding in every:
        for key in ("method_ref", "check_type", "verdict", "evidence", "claim", "rollback", "ready_to_land"):
            assert key in finding
        assert finding["claim"]["replay_command"]
        assert finding["verdict"] in mech.VERDICTS
    for card in payload["cards"]:
        assert card["code_conflict"]["verdict"] == "manual_review"
    hold = [c for c in payload["cards"] if "hold" in c["method_ref"]]
    assert hold == []  # hold card excluded by selection criteria
    skipped_refs = {s["method_ref"] for s in payload["selection"]["skipped"]}
    assert "method:card-hold-c-000000000000" in skipped_refs
