# CLI v2 execution

Goal: f3ca85bb-9b12-4c05-8bb0-9b17cdf8437c

Specification: LFL-CLI评估与需求实现计划-20261018.md, frozen design v2.
Frozen SHA256: `3bff19001452387db1d1378c1e0f36763c5cfbaad3fba0d3fca107b8bd4b4630`.
Base: `e3424f615b6312c2e6331faa762adeb423003bfa`.
Branch: `feat/cli-ux-20261018`.

**Active integration candidate. Initial CLI work is independently reviewed, committed,
and R9/install-validated; integration has not merged into main, been pushed, or deployed.**
The user explicitly requested creation of this Goal and implementation until completion.
A later automatic approval review rejected the next real GLM-5.3 review because private
patch disclosure to that external provider needs explicit authorization. Do not retry
indirectly or substitute another model. Local implementation and targeted checks continued.

## Candidate scope

The CLI is now a frontend adapter. Existing BackgroundRunner/EventBus own run lifecycle;
cancellation binds the exact session and generation. The terminal package owns text/JSON/
JSONL presentation, safe display, composer, explicit local commands and read-only queries.
No additional model policy, semantic success judge, scheduler or conversation store is added.

| Requirement | Candidate implementation / remaining acceptance |
| --- | --- |
| R01 | Authoritative incomplete/truncated/projection/cancel facts drive nonzero status; shell exit versus turn status documented |
| R02 | Effective interactive approval; non-TTY never consumes pipeline approval |
| R03 | Exact stdin/UTF-8 file, conflict checks, explicit startup model failure stops |
| R04 | Native runner streaming and generation-bound cancel; SIGTERM/BrokenPipe facts; real-provider/tool physical settlement and broader interruption matrix remain |
| R05 | text stdout versus stderr; one JSON object or sequenced JSONL; delivery unknown on broken pipe |
| R06 | Stateless new help/query namespaces; legacy command-specific pre-bootstrap parsing/help remains to be unified |
| R07 | Full IDs, search/show/export; native workspace mapping, owner/deletion validation, native event replay; no Engine/bootstrap |
| R08 | Safe configured-model catalog/identity; actual generation model from LoopResult; installed/source/service identity aggregation remains |
| R09 | prompt_toolkit composer, multiline, bracketed paste, in-memory per-session history/search, external editor; typing next draft during active run remains |
| R10 | Exact UTF-8 message file plus complete stored JSON/Markdown export; @ path completion does not silently read/upload |
| R11 | Usage and migration docs plus 61 existing install-workflow regressions; committed wheel/sdist and clean installed-candidate qualification passed for the pre-integration commit; requalify the integrated commit before release |
| R12 | Separate upgrade-execution G milestone; not claimed implemented by this frontend patch |
| R13 | Adaptive inline composer/status, themes, on-demand Markdown/code rendering; live Markdown block rendering remains |
| R14 | Native editing/history plus Ctrl+X application actions, contextual completion/approval, user binding validation/disable/reset; visible prefix timeout and full 29-action matrix remain |
| R15 | Slash-command and @ path completion, palette discovery, explicit selection; rich selectable palette/file ingestion remains |
| R16 | Transcript/details/stored diff/raw/render/copy/new-file export; advanced indexed navigation/horizontal diff viewer remains |
| R17 | Read-only native session/Goal/Task/child state; no implicit delegation; advanced sidebar optional F |
| R18 | Native approval callback marshalled to input owner, full safe arguments/default deny; expanded approval interruption PTY cases remain |
| R19 | Plain/dumb/non-TTY, safe control-character rendering and POSIX terminal restore; 3 real PTY layouts pass; remaining T01–T18 manual/SSH/tmux/IME/platform matrix remains |
| R20 | User-owned atomic display preferences, themes/width/keybindings separate from permissions; optional advanced status/notifications remain |

This table distinguishes working candidate code from final acceptance. It is not a claim
that all 20 requirements or phases A–E are complete.

## Evidence

- Original A contract tests on baseline: **21 failed, 2 passed**.
- Current CLI/terminal/native-runner/storage/PTY/architecture targeted suite:
  **158 passed, 3 pre-existing warnings**.
- Existing installation/doctor/upgrade-preflight/committed-distribution-builder regressions:
  **61 passed**.
- Changed Python Ruff: **PASS**. Scoped Pyright: **0 errors, 0 warnings**.
- `git diff --check`: **PASS**. `uv lock --check --offline`: command succeeded.
- PTY layouts: 60×12, 100×24, 140×30. Verified Unicode/combining emoji, exact multiline
  bracketed paste without implicit submit, explicit send, ordinary cooked input/echo
  handoff, then all original termios attributes (no masked flags). Darwin PENDIN is
  transient until the handoff read; the test exercises that read explicitly.
- The local editable installation is built from this candidate's locked dependencies;
  it is not a committed wheel/sdist or a production installation qualification.

Logs under ignored task-owned `data/cli-ux-*.log` preserve actual commands/results.
The original full R9 subsequently **ran to completion and passed** on commit
`f348dd6e18d8a28c1f8d9794f0eacac52854f348`: 9,520 passed / 142 skipped /
0 failed, with Ruff, Pyright, environment, Tier-0 and final guards green.
Log SHA256: `84782bf87a089bc460173408e1e07a906c754fb44261e8a78ca45586e66baae1`.
The frozen clean commit produced a wheel and sdist offline, and the wheel passed fresh-venv
offline installed smoke: 345 resource hashes, Web health/UI 200, correct workspace,
0 real Provider calls and no source-checkout path. The wheel was **not** signed or
published. These facts qualify the pre-integration CLI tree, not this new combined tree.

## Independent review record

The original 27-file candidate received a genuine, completed, isolated GLM-5.3 full review:
`subagent_325b99246b98`, result `result-3991bf7cf667433291c546a97f190307`, source SHA
`c7c248bd9d63513fd6c197f05d8e723f10809d923575845642c3812003652b98`, PASS, P0/P1=0,
P2=2. It identified the installed legacy query root and failed startup model leaving a new
empty session. Both were fixed with RED→GREEN tests. The exact three-file delta received
isolated reviewer `subagent_cf1871aaf86b`, result `result-5cf82d76e0a84b65b0fcd1ee4bcc9539`,
PASS, P0/P1=0, P2=1 (only the pathological empty-string session ID boundary).

The original full R9 then exposed two additional genuine regressions: a legacy approval test
did not model TTY, and five direct process-environment reads violated the architecture
ratchet. Both were fixed without loosening the ratchet. The exact four-file delta received
isolated reviewer `subagent_d2bd11393b92`, result `result-df6f912e9989468fb56fdf12e8c01213`,
PASS, P0/P1/P2=0. The final staged/source SHA was
`a32a3adfa488d5ed3e2d21c91e4bd0cf22abbfe96e49e3f1aefb0c2264ea683e`.

That exact source tree was committed as `f348dd6e18d8a28c1f8d9794f0eacac52854f348` and
passed original R9 (9,520 passed / 142 skipped / 0 failed). A clean offline wheel build and
fresh-venv installed smoke also passed. This evidence applies to that source commit, not the
new combined tree based on `59f51e3e`; the integration delta below needs its own review and R9.

## Next work

1. Initial independent GLM-5.3 full PASS and two exact narrow PASS reviews completed;
   3 RED defects and 2 full-R9 defects fixed with regression evidence, no ratchet widening.
2. Initial source candidate passed original full R9 and fresh-installed wheel/sdist smoke.
3. New independent integration worktree at `59f51e3e` retains main's upgrade/start/extensions
   capabilities and adds detailed CLI help. Integration candidate still requires focused
   tests, a new GLM-5.3 merge review and original full R9 on **its own** final tree.
4. Obtain specific authorization before any actual local `main` merge; do not interpret
   isolated integration, commit or smoke as production installation or release.
5. Continue outstanding mandatory CLI acceptance, keep optional F/G separately scoped,
   and mark this Goal complete only after its mandatory scope and integration are truly met.
   Never label the optional F/G milestones or unverified platforms complete by implication.
