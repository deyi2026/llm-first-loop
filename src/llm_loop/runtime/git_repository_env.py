"""Shared environment boundary for explicit-root Git operations."""

from __future__ import annotations

from llm_loop.runtime.resolver import legacy_env_snapshot

# Repository-local variables plus explicit external configuration overrides.
# The explicit cwd, not the caller's Git process, owns these operations.
GIT_REPO_ENV_VARS = frozenset({
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT", "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE", "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX",
    "GIT_SHALLOW_FILE", "GIT_COMMON_DIR", "GIT_NAMESPACE",
    "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
})


def git_repository_env() -> dict[str, str]:
    """Environment for Git operations bound to an explicit repository path."""
    return {key: value for key, value in legacy_env_snapshot().items() if key not in GIT_REPO_ENV_VARS}
