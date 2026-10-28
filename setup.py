"""Bundle immutable application resources; editable installs keep source layout."""

import hashlib
import json
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
DOCS = (
    "ai_rules.md", "ai_rules.lite.md", "configuration.md",
    "DEVELOPMENT_REPAIR_SAFETY.md", "governance/card-lifecycle.md",
)
EXCLUDED = {"__pycache__", "node_modules"}


def resource_files():
    for name in DOCS:
        yield ROOT / "docs" / name, Path("docs") / name
    for name in ("skills", "methods", "webui/dist"):
        base = ROOT / name
        if not base.is_dir():
            raise RuntimeError(f"Missing application resources: {name}; build Web UI first")
        for source in sorted(base.rglob("*")):
            relative = source.relative_to(ROOT)
            if any((p.startswith(".") and p != ".lfl-webui-source.json") or p in EXCLUDED for p in relative.parts):
                continue
            if source.is_file() and not any(p.is_symlink() for p in (source, *source.parents)):
                yield source, relative


class BuildApplication(build_py):
    def run(self):
        super().run()
        if self.editable_mode:
            return
        if not (ROOT / "webui/dist/index.html").is_file():
            raise RuntimeError("Missing Web UI: run npm ci && npm run build in webui before building")
        target = Path(self.build_lib) / "llm_loop" / "_bundled"
        if target.exists():
            shutil.rmtree(target)
        hashes = {}
        for source, relative in resource_files():
            if not source.resolve().is_relative_to(ROOT) or source.is_symlink():
                raise RuntimeError(f"Resource escapes application source: {relative}")
            content = source.read_bytes()
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            hashes[relative.as_posix()] = hashlib.sha256(content).hexdigest()
        manifest = {
            "schema": "lfl.application-bundle/v1",
            "version": self.distribution.get_version(),
            "files": hashes,
        }
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


setup(cmdclass={"build_py": BuildApplication})
