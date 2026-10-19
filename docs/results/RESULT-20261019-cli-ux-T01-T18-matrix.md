# LFL CLI T01-T18 acceptance matrix (isolated, not released)

Date: 2026-10-19. Scope: R14-R16/R18-R19 candidate based on isolated R13
commit 729b8a441c9596799803f37ac4590d91624bb5df. This is **not** a claim
of independent review, full R9, integration or installation acceptance.

macOS local POSIX PTY, fake Provider inputs and no external model call.
From this worktree the targeted command was:

    PYTHONPATH=src ../../.venv/bin/python -m pytest
      tests/unit/test_terminal_cli.py tests/unit/test_terminal_preinput.py
      tests/unit/test_terminal_pty.py tests/unit/test_terminal_markdown_stream.py
      tests/unit/test_terminal_keymap.py tests/unit/test_terminal_palette.py
      tests/unit/test_terminal_palette_pty.py tests/unit/test_terminal_record_browser.py
      tests/unit/test_terminal_approval_interrupt.py -q

All the test paths above were supplied in one command (line wraps are for display).
Actual final result: **197 passed / 0 failed**, 10.04 s. Evidence: task-owned ignored
file data/cli-r14-r19-extended-v3.log. Modified-source Ruff: PASS. A prior
157-case run had one SIGTERM/PTY timeout; isolated baseline reproduction of
that case passed, and the final combined 197-case run passed. The earlier
timeout is retained as evidence, not erased.

| ID | Qualification | Actual evidence / remaining boundary |
| --- | --- | --- |
| T01 | AUTOMATED_PASS | Real PTY 60x12, 100x24, 140x30 and SIGWINCH 80x24 to 120x40, 120x40 to 48x12, 48x12 to 80x24; composer/restoration |
| T02 | AUTOMATED_PASS | Real PTY 100 lines of bracketed paste with CJK, combining marks and blank lines; explicit submit preserves exact text |
| T03 | PARTIAL | Explicit multi-line mode and backslash/Enter plus dumb fallback verified; modified Shift+Enter/Meta translation varies by terminal |
| T04 | MANUAL_PENDING | CJK/emoji/combining paste covered; physical IME candidate-confirm interactions still require human input |
| T05 | AUTOMATED_PASS | Real PTY Tab completes /help without premature submit; palette Esc cancels and Tab/Enter selects /help, both preserve draft and terminal modes |
| T06 | AUTOMATED_PASS | Native BackgroundRunner exact-generation Ctrl+C and next-turn draft cancellation/settlement tests |
| T07 | PARTIAL | 29-action map, reserved keys, approval default-deny/close/late-yes tested; complete PTY focus-switch matrix still pending |
| T08 | PENDING | Browser anchors/paging are present, but streaming while viewing older records and new-item count not yet integrated in inline UI |
| T09 | PARTIAL | Stored exact diff, /raw, 10k-line paging; physical clipboard and horizontal diff viewer not fully qualified |
| T10 | AUTOMATED_PASS | NO_COLOR, exact raw/JSON, multiple themes and explicit text statuses in CLI/Markdown tests |
| T11 | AUTOMATED_PASS | Real dumb PTY multiline and linear plain rendering without cursor-control dependence |
| T12 | AUTOMATED_PASS | Real PTY SIGTERM, running-draft abort, termios restoration, failed external editor preserves draft |
| T13 | MANUAL_PENDING | Apple Terminal/iTerm2/VS Code, SSH/tmux and native Linux terminal actual builds not exercised by macOS PTY |
| T14 | PARTIAL | Browser cursor per session, session/workspace identity and preinput/run separation tested; live child events during browsing not |
| T15 | AUTOMATED_PASS | JSON/JSONL exact protocol, non-TTY fallback, BrokenPipe and unknown-settlement tests |
| T16 | AUTOMATED_PASS | Binding conflict/reserved keys/disable/reset and corrupt UI config fallback; no model-policy modification |
| T17 | NOT_APPLICABLE | Optional full-screen feature F not enabled; no full-screen success claim |
| T18 | PARTIAL | Existing 10,000 fake-event protocol test proves exact sequence, bounded 8 MiB peak, p95 under 200ms; real PTY high-volume redraw/keyboard responsiveness pending |

AUTOMATED_PASS means the stated executable assertions actually ran on this Mac.
PARTIAL means only part of the criterion is covered; MANUAL_PENDING means the
target terminal was not available; PENDING is a functional gap;
NOT_APPLICABLE means a not-yet-enabled optional feature.

Next: address reachable gaps without a new rendering framework, obtain a fresh
independent GLM-5.3 Reviewer for the exact final candidate (PASS, P0/P1=0),
then original full R9 and isolated commit. Linux/SSH/tmux/IME qualifications
require their actual target terminal. A macOS PTY is not interchangeable.
