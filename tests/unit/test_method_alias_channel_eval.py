"""Guards for the method-retrieval eval instrument.

Two failure modes are locked here:
1. the harness scoring code imported from outside <repo>/src (a .releases/ snapshot);
2. the alias ablation switch silently doing nothing, which would let an A/B report
   a delta that no code path can produce.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "evals/retrieval_ab/run_method_semantic_baseline.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("method_semantic_baseline_harness", HARNESS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_guard_rejects_release_snapshot_path():
    harness = _load_harness()
    snapshot = ROOT / ".releases/cdcd0c3a32d856eb2563d386ef98118bd82bb603/src/llm_loop/__init__.py"
    assert harness.is_working_tree_module(str(snapshot), ROOT / "src") is False


def test_guard_accepts_working_tree_path():
    harness = _load_harness()
    assert harness.is_working_tree_module(str(ROOT / "src/llm_loop/__init__.py"), ROOT / "src") is True


def _write_card(root: Path, method_id: str, *, description: str, body: str, aliases: str = "") -> None:
    card = root / method_id
    card.mkdir(parents=True)
    front = [
        "---",
        f"method_id: {method_id}",
        "name: Alias Probe Card",
        f"description: {description}",
        "status: candidate",
    ]
    if aliases:
        front.append(f"aliases: {aliases}")
    front.append("---")
    (card / "METHOD.md").write_text("\n".join(front) + "\n" + body.strip() + "\n", encoding="utf-8")


def test_alias_ablation_actually_removes_the_alias_channel(tmp_path: Path):
    harness = _load_harness()
    corpus = tmp_path / "methods"
    corpus.mkdir()
    _write_card(corpus, "alias-probe-card", description="plain card", body="# Body\nnothing matching here", aliases="xylophone")
    _write_card(corpus, "control-card", description="plain card", body="# Body\nnothing matching either")

    from llm_loop.methods.store import MethodStore

    live = MethodStore(str(corpus), workspace_root=str(tmp_path))
    assert [card["id"] for card in live.list("xylophone")] == ["alias-probe-card"]

    ablated = harness.without_aliases(MethodStore(str(corpus), workspace_root=str(tmp_path)))
    assert [card["id"] for card in ablated.list("xylophone")] == []


def test_alias_batch_ablation_only_touches_named_cards(tmp_path: Path):
    harness = _load_harness()
    corpus = tmp_path / "methods"
    corpus.mkdir()
    _write_card(corpus, "card-a", description="plain card", body="# Body\nnothing matching here", aliases="xylophone")
    _write_card(corpus, "card-b", description="plain card", body="# Body\nnothing matching either", aliases="xylophone")

    from llm_loop.methods.store import MethodStore

    partial = harness.without_aliases(
        MethodStore(str(corpus), workspace_root=str(tmp_path)),
        only_ids=frozenset({"card-a"}),
    )
    assert [card["id"] for card in partial.list("xylophone")] == ["card-b"]
