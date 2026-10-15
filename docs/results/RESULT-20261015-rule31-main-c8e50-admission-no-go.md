# Rule31 latest-main admission — evidence-based NO_GO

Date: 2026-10-15. Goal: 9956a550-f1ad-4281-aeb4-a4e797fe85ca.

## Decision: NO_GO (upstream static diagnostics)

Latest-main snapshot: `c8e50cb2b16c067a22609285d6aaa5eadf3ebdac`.
New isolated worktree: `.worktrees/rule31-main-c8e50-admission-20261015`.
New isolated branch: `fix/rule31-main-c8e50-admission-20261015` (no source commit).

The prior reviewed Rule31 eight-file source patch was transferred verbatim onto the latest clean main:
- Git binary staged patch size **24,049 bytes**, SHA-256 `705c094eb0c4b3d6bc82a69bacc0190e0d126d30df8eb9094cc10ddedd681e4f`.
- Changes limited to the same 8 files; staged diff-check and latest-main `scripts/git_security_scan.sh --staged` PASS.
- No changed-path overlap between old `main@db4aaa856` and latest `main@c8e50cb2` for the eight source paths or `docs/ai_rules.md`.
- Rule31/backup/browser/usage_net focused suite **90 passed**. Original ignored log `data/rule31-main-c8e50-admission-20261015/focused.log`, SHA-256 `5b8b56a42e947b70f4d006e0371ae7a985ec3731405aaa7ba0133697ec3e3bd2`.
- No active canonical CI or Reviewer process during preflight; main tracked status was clean. Other worktrees untouched.

Original repository `bash scripts/ci_gate.sh --quick` with project venv and API-key environment variables unset **exited 1** before WebUI build/tier0:
- Ruff ratchet PASS (historical 67, current 35, new 0, changed-file 0).
- Env-pin declaration PASS (858 test files).
- Pyright ratchet **DENIED**: historical 45, current 24, **5 new diagnostics**, changed-file diagnostics 0.
- Five new fingerprints exclusively in `src/llm_loop/knowledge/jev/wire.py`: two groups `reportArgumentType` for `Unknown | None` to `float` and one `reportOptionalMemberAccess` for `.items()` on possibly `None`.

**Independent clean-main reproduction:** created a detached clean worktree at exactly c8e50cb2, ran the unmodified `scripts/check_static_diagnostics.py --tool pyright` in project venv. It returned **the same five** Pyright diagnostics with `changed_python_files=0`, exit 1. JEV file blob equals the authoritative main blob `f857b89594f9193d2ee70a11dc204d06f000600d`. The owned temporary comparison worktree was verified clean and removed without force. This proves the error predates the Rule31 change in the newest main.

Original ignored local logs:
- Candidate quick (exit 1): `data/rule31-main-c8e50-admission-20261015/quick.log` SHA-256 `2fae6ecdd08144f2ab7949d3882db7691b2d18a5b546c73a35c9054bbd078e35`.
- Clean-main baseline Pyright (exit 1): `data/rule31-main-c8e50-admission-20261015/baseline-pyright.log` SHA-256 `81b0ba34498bc7121d540b2ac0363b744bac7bcbcb6c197bfeba12a16a52fd33`.

## Required stop boundaries

- No GLM-5.3 Reviewer was invoked for this new baseline. The reviewer launcher was merely prepared and its provider-free preflight passed; it was not executed after static NO_GO. No current-main review qualification exists.
- No canonical full R9 was started. Previous full R9 from the older db4aaa856 candidate does **not** qualify this new main.
- No source commit, main merge, push, publish, restart, G4 or production Provider mutation.
- No baseline/known-red ratchet expansion, skip, ci_gate modification, or quiet diagnostic suppression. The eight-file patch remains staged and recoverable in its unique isolated worktree.
- Other Rule28, Rule31 and Jev agents' worktrees and untracked main data were not touched.

## Separate upstream JEV fix proposal (NOT executed)

The JEV changes belong in a **separate, independent source-owner branch and review**, not a hidden ninth Rule31 file:

1. In `src/llm_loop/knowledge/jev/wire.py` make the valid-choice branch explicitly check `isinstance(probabilities, dict)` and `isinstance(confidence, (int, float))` before `probabilities.items()` and `float(confidence)`.
2. In the valid-score branch explicitly check `isinstance(confidence, (int, float))` before `float(confidence)`. These predicates are logically implied by the original finite/value checks. Preserve the runtime validation semantics and invalid-reason codes. Do not cast arbitrary unknown input to float just to silence Pyright.
3. Independently review the exact JEV patch and rerun JEV regression, Ruff and original Pyright ratchet, then upstream it through the designated main process.
4. After main's static gate is actually green, freeze another current-main Rule31 candidate, run a fresh Reviewer and unmodified canonical full R9, then only local isolation commit. Any main merge, push or deployment still requires separate approval.

This is evidence of a blocked admission, **not** a deployment or completed latest-main integration.
