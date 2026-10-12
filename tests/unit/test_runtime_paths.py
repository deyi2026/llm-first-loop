from pathlib import Path

from llm_loop.runtime.paths import resolve_runtime_paths


def test_mutable_knowledge_follows_persistent_data_dir_not_cwd(tmp_path):
    canonical = tmp_path / "canonical"
    data_dir = canonical / "data"
    code_root = tmp_path / "sidecar"
    data_dir.mkdir(parents=True)
    code_root.mkdir()

    paths = resolve_runtime_paths(data_dir=data_dir, code_root=code_root, env={})

    assert paths.state_root == canonical.resolve()
    assert paths.experiences_dir == (canonical / "experiences").resolve()
    assert paths.methods_dir == (data_dir / "methods").resolve()
    assert paths.method_seed_dir == (code_root / "methods").resolve()
    assert paths.skills_dir == (code_root / "skills").resolve()
    assert paths.docs_dir == (code_root / "docs").resolve()
    assert paths.experiences_source == "data_dir_inferred"
    assert paths.methods_source == "data_dir_inferred"
    assert paths.auto_rebind_applied is True


def test_explicit_knowledge_overrides_win_without_copying(tmp_path):
    data_dir = tmp_path / "state" / "data"
    code_root = tmp_path / "code"
    explicit_exp = tmp_path / "operator" / "experiences"
    explicit_methods = tmp_path / "operator" / "methods"
    data_dir.mkdir(parents=True)
    code_root.mkdir()

    paths = resolve_runtime_paths(
        data_dir=data_dir,
        code_root=code_root,
        env={
            "EXPERIENCES_DIR": str(explicit_exp),
            "METHODS_DIR": str(explicit_methods),
        },
    )

    assert paths.experiences_dir == explicit_exp.resolve()
    assert paths.methods_dir == explicit_methods.resolve()
    assert paths.experiences_source == "explicit_env"
    assert paths.methods_source == "explicit_env"
    assert paths.auto_rebind_applied is False


def test_bundle_shaped_data_dir_keeps_all_mutable_state_inside_bundle(tmp_path):
    data_dir = tmp_path / "isolated-state"
    code_root = tmp_path / "code"
    data_dir.mkdir()
    code_root.mkdir()

    paths = resolve_runtime_paths(data_dir=data_dir, code_root=code_root, env={})

    assert paths.state_root == data_dir.resolve()
    assert paths.experiences_dir == (data_dir / "experiences").resolve()
    assert paths.methods_dir == (data_dir / "methods").resolve()


def test_load_settings_materializes_persistent_knowledge_paths(tmp_path, monkeypatch):
    from llm_loop.config import load_settings

    canonical = tmp_path / "canonical"
    data_dir = canonical / "data"
    data_dir.mkdir(parents=True)
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    # 真实仓根 .env 的 EXPERIENCES_DIR 等五键会被 load_settings 回填为 explicit_env
    # 并压过 DATA_DIR 推断；把 runtime root 指到空目录隔离该回填（无 .env → parse 空）。
    monkeypatch.setenv("LFL_RUNTIME_ROOT", str(tmp_path))
    # LFL_DATA_DIR 优先级高于 DATA_DIR：服务进程环境常驻该键，不清则泄漏进
    # 断言（2026-09-29 实测：binding data_dir_source=explicit_env 指向真实工作区）。
    monkeypatch.delenv("LFL_DATA_DIR", raising=False)
    for key in ("EXPERIENCES_DIR", "METHODS_DIR", "METHOD_SEED_DIR", "SKILLS_DIR", "DOCS_DIR"):
        monkeypatch.delenv(key, raising=False)

    settings = load_settings()

    assert Path(settings.experiences_dir) == (canonical / "experiences").resolve()
    assert Path(settings.methods_dir) == (data_dir / "methods").resolve()
    assert Path(settings.method_seed_dir).is_absolute()
    assert Path(settings.skills_dir).is_absolute()
    assert Path(settings.docs_dir).is_absolute()
    paths = settings._extra["runtime_paths"]
    assert paths.auto_rebind_applied is True


def test_linked_worktree_without_data_dir_anchors_state_to_git_common_root(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    side = tmp_path / "sidecar"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Runtime Paths Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "runtime-paths@example.invalid"], cwd=repo, check=True)
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "worktree", "add", "-q", "-b", "side", str(side)], cwd=repo, check=True)

    paths = resolve_runtime_paths(
        data_dir=None,
        code_root=side,
        env={},
        data_dir_explicit=False,
    )

    assert paths.git_common_root == repo.resolve()
    assert paths.data_dir == (repo / "data").resolve()
    assert paths.data_dir_source == "git_common_root"
    assert paths.data_dir_auto_rebind is True
    assert paths.state_root == repo.resolve()


def test_skills_follow_primary_worktree_from_linked_sidecar_without_publish(tmp_path):
    """2026-10-12 owner directive (RULE-AI-28 配套): 新工作区 skill 无需 publish 即入注册表.

    从 linked sidecar worktree（发布快照）运行时，skills_dir 必须解析到主工作树，
    让工作区新增 skill 立即可见；显式 SKILLS_DIR 仍然最优先。
    """
    import subprocess

    repo = tmp_path / "repo"
    side = tmp_path / "sidecar"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Runtime Paths Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "runtime-paths@example.invalid"], cwd=repo, check=True)
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "worktree", "add", "-q", "-b", "side", str(side)], cwd=repo, check=True)

    (repo / "skills" / "live-skill").mkdir(parents=True)
    (repo / "skills" / "live-skill" / "SKILL.md").write_text(
        "---\nname: live-skill\n---\n", encoding="utf-8"
    )
    (side / "skills" / "snapshot-skill").mkdir(parents=True)
    (side / "skills" / "snapshot-skill" / "SKILL.md").write_text(
        "---\nname: snapshot-skill\n---\n", encoding="utf-8"
    )

    paths = resolve_runtime_paths(data_dir=None, code_root=side, env={})

    assert paths.skills_dir == (repo / "skills").resolve()

    # loader 层判别性 pin：live-skill 可见、snapshot-skill 不可见（P2-4 加固）
    from llm_loop.skills.loader import scan_skills_dir

    assert [m.name for m in scan_skills_dir(paths.skills_dir)] == ["live-skill"]

    explicit = resolve_runtime_paths(
        data_dir=None, code_root=side, env={"SKILLS_DIR": str(side / "skills")}
    )
    assert explicit.skills_dir == (side / "skills").resolve()


def test_explicit_data_dir_inside_linked_sidecar_is_preserved_but_marked_unsafe(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    side = tmp_path / "sidecar"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Runtime Paths Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "runtime-paths@example.invalid"], cwd=repo, check=True)
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "worktree", "add", "-q", "-b", "side", str(side)], cwd=repo, check=True)

    paths = resolve_runtime_paths(
        data_dir=side / "data",
        code_root=side,
        env={},
        data_dir_explicit=True,
    )

    assert paths.data_dir == (side / "data").resolve()
    assert paths.data_dir_source == "explicit"
    assert paths.explicit_sidecar_state is True
    # 隔离只约束可变知识写入；skills 读取源仍跟随主工作树（P2-2 加固，2026-10-12）
    assert paths.skills_dir == (repo / "skills").resolve()

    from llm_loop.runtime.knowledge_health import inspect_knowledge_health

    (side / "methods" / "seed").mkdir(parents=True)
    (side / "methods" / "seed" / "METHOD.md").write_text("x\n", encoding="utf-8")
    (side / "skills" / "probe").mkdir(parents=True)
    (side / "skills" / "probe" / "SKILL.md").write_text("x\n", encoding="utf-8")
    (side / "docs").mkdir()
    (side / "docs" / "ai_rules.md").write_text("## RULE-AI-00\nprobe\n", encoding="utf-8")
    health = inspect_knowledge_health(paths)
    assert health["status"] == "quarantined"
    assert health["writes_enabled"] is False
    assert "explicit_sidecar_state_root" in health["reasons"]
