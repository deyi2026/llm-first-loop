"""CatastrophicGuard path-identity regression. Never execute deletion commands.

Only the guard classifier is invoked; symlinks are created inside pytest's
temporary directory and no protected/system files are written.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from llm_loop.tools.safety import CatastrophicGuard


def _blocked(command: str) -> bool:
    verdict = CatastrophicGuard(audit_dir=None).guard(
        "execute_command", {"command": command}
    )
    return bool(verdict is not None and verdict.blocked)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    location = tmp_path / "home"
    location.mkdir()
    monkeypatch.setenv("HOME", str(location))
    monkeypatch.chdir(location)
    return location


@pytest.mark.parametrize("target", ["/", "/etc", "/var", "/home", "/usr"])
def test_dotdot_escape_from_home_blocks_canonical_system_targets(
    home: Path, target: str,
) -> None:
    alias = home / os.path.relpath(target, home)
    assert os.path.realpath(alias) == os.path.realpath(target)
    assert _blocked(f"rm -rf -- {alias}")
    assert _blocked(f"find {alias} -name '*.log' -delete")


@pytest.mark.parametrize("target", ["/", "/etc", "/var", "/home", "/usr"])
def test_system_targets_with_normalized_and_literal_names(
    home: Path, target: str,
) -> None:
    assert _blocked(f"rm -rf -- {target}")
    assert _blocked(f"find {target} -delete")


def test_symlink_inside_home_to_critical_directory_is_blocked(home: Path) -> None:
    alias = home / "indirection"
    alias.symlink_to("/etc", target_is_directory=True)
    assert _blocked(f"rm -rf -- {alias}")
    assert _blocked(f"rm -rf -- {alias}/hosts")
    assert _blocked(f"find {alias} -delete")
    assert _blocked(f"find -L {alias} -type f -delete")


def test_symlink_inside_home_to_normal_home_subdir_remains_allowed(home: Path) -> None:
    legit = home / "disposable"
    legit.mkdir()
    alias = home / "legitimate-alias"
    alias.symlink_to(legit, target_is_directory=True)
    assert not _blocked(f"rm -rf -- {alias}")
    assert not _blocked(f"find {alias} -name '*.tmp' -delete")


def test_home_itself_blocked_but_ordinary_descendants_allowed(
    home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _blocked(f"rm -rf -- {home}")
    assert _blocked("rm -rf ~")
    assert _blocked("rm -rf -- .")  # cwd is HOME itself: relative alias is still destructive
    assert _blocked("find . -delete")
    assert not _blocked("rm -rf ~/build")
    assert not _blocked("rm -rf $HOME/projects")
    assert not _blocked(f"rm -rf -- {home}/data")
    workspace = home / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    assert not _blocked("find . -name '*.log' -delete")


def test_relative_target_escape_and_normal_relative_are_distinguished(home: Path) -> None:
    to_etc = os.path.relpath("/etc", home)
    assert _blocked(f"rm -rf -- {to_etc}")
    assert _blocked(f"find {to_etc} -delete")
    assert not _blocked("rm -rf -- ./build")


@pytest.mark.parametrize(
    "command",
    [
        "sudo rm -rf -- /etc",
        "sudo -n -u root rm -rf /var",
        "env TEST_VALUE=ok /bin/rm -rf -- /etc",
        "command rm -rf -- /etc",
        "sudo sh -c 'rm -rf -- /etc'",
        "env TEST_VALUE=ok sh -c 'rm -rf -- /'",
        "nohup /bin/rm -rf -- /etc",
    ],
)
def test_execution_prefix_does_not_bypass_protected_paths(
    home: Path, command: str,
) -> None:
    assert _blocked(command)


@pytest.mark.parametrize(
    "command",
    [
        "sudo rm -rf -- ~/build",
        "command rm -rf -- $HOME/projects",
        "env TEST_VALUE=ok /bin/rm -rf -- ./build",
        "echo rm -rf /etc",  # mere mention of a deletion is not execution
        "find . -name '*.tmp' -delete",
    ],
)
def test_benign_wrapper_and_shell_text_is_not_overblocked(
    home: Path, command: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = home / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    assert not _blocked(command)
