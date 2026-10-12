"""Static contracts that keep heavyweight optional renderers out of the first-load bundle."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEBUI_SRC = ROOT / "webui" / "src"


def test_katex_is_lazy_and_owned_by_dedicated_renderer_chunk() -> None:
    markdown = (WEBUI_SRC / "core" / "markdown.ts").read_text(encoding="utf-8")
    renderer_path = WEBUI_SRC / "core" / "mathRenderer.ts"
    message_item = (WEBUI_SRC / "components" / "conversation" / "MessageItem.tsx").read_text(
        encoding="utf-8"
    )
    file_preview = (WEBUI_SRC / "components" / "FilePreviewView.tsx").read_text(encoding="utf-8")

    assert 'from "katex"' not in markdown
    assert 'katex/dist/katex.min.css' not in markdown
    assert 'import("./mathRenderer")' in markdown
    assert renderer_path.exists()

    renderer = renderer_path.read_text(encoding="utf-8")
    assert 'from "katex"' in renderer
    assert 'katex/dist/katex.min.css' in renderer
    assert "ensureMathRenderer()" in message_item
    assert "hasMathCandidate(text)" in message_item
    assert "ensureMathRenderer()" in file_preview
    assert "hasMathCandidate(markdownSource)" in file_preview
