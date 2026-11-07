# scripts/systemd — 三服务 systemd user unit 参考样本（DESIGN-20261107 §4.1/§4.2）

本目录是**参考样本，不是安装真值**：

- 四个 unit 文本（`lfl.service` / `lfl-feishu.service` / `lfl-learning.service` / `lfl-recovery.service`）展示
  默认安装根（`%h/.local/share/lfl`）形态；由
  `src/llm_loop/runtime/installation.py::render_unit_text` 生成，一致性由
  `tests/unit/test_install_upgrade_recovery.py` 锁定。
- 安装器（`scripts/install_linux.sh`）按解析后的 `LFL_HOME` 调用
  `python -m llm_loop.runtime.installation install-units` 生成真实 unit：
  自定义根写绝对路径（三处一致），生成后 `systemd-analyze --user verify` 校验，
  失败即 fail-closed（不 daemon-reload、不 enable）。
- 稳定启动器 `LFL_HOME/bin/lfl-service` 绑定具体安装根，无可移植静态形态，
  由 `render_lfl_service_launcher` 动态生成；版本唯一真值是
  `.LFL-active-version`，unit 内不出现版本目录。
- 样本再生成（worktree 内开发）：
  `PYTHONPATH=src .venv/bin/python -c "from llm_loop.runtime.installation import _regen_samples_main as m; m()"`
