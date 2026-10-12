#!/usr/bin/env bash
# Source-only helper: consume the whole listing before testing exact ownership.

r9_cleanup_probe() {
  local probe_path="$1" listing
  if ! listing="$(git worktree list --porcelain)"; then
    echo "PROBE cleanup failed: cannot list registered worktrees ($probe_path)" >&2
    return 1
  fi
  # grep without -q consumes every byte. An early reader would SIGPIPE git
  # under pipefail and silently skip cleanup as the worktree list grows.
  if printf '%s\n' "$listing" | grep -Fx "worktree $probe_path" >/dev/null; then
    if ! git worktree remove --force "$probe_path"; then
      echo "PROBE cleanup failed: cannot remove owned worktree ($probe_path)" >&2
      return 1
    fi
  fi
}
