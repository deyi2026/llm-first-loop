"""Operator-configured model roles shared by routing and isolated reviewers.

LFL_MODEL_ROLES is a JSON object mapping role names to ordered canonical
provider/model references. It contains no credentials or provider endpoints.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

from llm_loop.config import _raw_env
from llm_loop.runtime.resolver import parse_env_file

_ROLE_RE = re.compile(r"[a-z][a-z0-9_-]{0,47}\Z")
_MODEL_RE = re.compile(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")
_MAX_ROLES = 32
_MAX_CANDIDATES = 8


def parse_model_roles(raw: str) -> tuple[dict[str, tuple[str, ...]], str]:
    """Parse role mappings strictly; invalid configuration is never guessed."""
    if not str(raw or "").strip():
        return {}, ""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}, "model_roles_invalid_json"
    if not isinstance(value, Mapping) or not value or len(value) > _MAX_ROLES:
        return {}, "model_roles_invalid_shape"
    parsed: dict[str, tuple[str, ...]] = {}
    for role, candidates in value.items():
        if not isinstance(role, str) or not _ROLE_RE.fullmatch(role):
            return {}, "model_roles_invalid_role"
        if not isinstance(candidates, list) or not candidates or len(candidates) > _MAX_CANDIDATES:
            return {}, "model_roles_invalid_candidates"
        if any(
            not isinstance(item, str) or len(item) > 160 or not _MODEL_RE.fullmatch(item)
            for item in candidates
        ):
            return {}, "model_roles_invalid_model_ref"
        if len(set(candidates)) != len(candidates):
            return {}, "model_roles_duplicate_candidate"
        parsed[role] = tuple(candidates)
    return parsed, ""


def reviewer_models_configured(raw: str, legacy_raw: str = "") -> str:
    """Return reviewer candidates in legacy wire format, without a built-in default.

    The legacy dedicated variable wins. Otherwise the explicitly configured
    `reviewer` role is used. An absent role remains unconfigured/fail-closed.
    """
    if str(legacy_raw or "").strip():
        return legacy_raw
    roles, error = parse_model_roles(raw)
    if error:
        return ""
    return ",".join(roles.get("reviewer", ()))


def model_roles_for_refresh(process_raw: str) -> str:
    """Read the operator's managed dotenv role value, not a stale startup copy.

    Only this non-secret setting is re-read; no global environment is mutated.
    An empty or removed key disables the managed mapping. A read error leaves
    the old mapping active. Unmanaged callers retain process-env semantics.
    """
    explicit = _raw_env("LFL_ENV_FILE").strip()
    runtime = _raw_env("LFL_RUNTIME_ROOT").strip()
    if not explicit and not runtime:
        return process_raw
    path = Path(explicit).expanduser() if explicit else Path(runtime).expanduser() / ".env"
    try:
        if not path.is_file():
            raise OSError("managed dotenv missing")
        return parse_env_file(path).get("LFL_MODEL_ROLES", "")
    except (OSError, UnicodeError) as exc:
        raise ValueError("model_roles_config_unreadable") from exc
