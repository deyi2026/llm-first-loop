"""One bounded, read-only GLM-5.3 editorial review through LFL Web.

This launches one new review session and persists the returned response.
It does not repeat on errors, publish, or change project source.
"""
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
MD = ROOT / "20261013-lfl-daily-15.md"
LEDGER = ROOT / "20261013-daily15-sources.md"
SOURCE = ROOT.parent / "results" / "RESULT-20261012-subagent-physical-cache-accounting.md"
IMAGES = [ROOT / "img" / f for f in (
    "fig43-one-prompt-many-calls.png",
    "fig44-logical-vs-physical.png",
    "fig45-cache-not-free.png",
    "fig46-four-denominators.png",
    "fig47-receipt-evidence-states.png",
    "fig48-six-questions.png",
)]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run():
    refs = [{"path": str(x.relative_to(ROOT.parent.parent)),
             "sha256": sha(x), "bytes": x.stat().st_size} for x in [MD, LEDGER, *IMAGES]]
    source = SOURCE.read_text()
    d07 = source[source.index("## D07 真实历史数据复算"):
                 source.index("## 负例与验收")]
    prompt = (
        "你是独立于作者的 LFL GLM-5.3 科普文章审稿员。只读审稿，不调用任何写入、"
        "发布、重启、删除或花费外部服务的工具，也不要给出伪造的工具证据。"
        "必须返回 PASS 或 REVISE；同时列出逐项可核查的具体依据、"
        "哪些内容本轮无法独立验证（UNVERIFIED）。\n"
        "检查范围：事实与营销语边界、数字自洽、图注准确性、"
        "模拟与真实指标严格隔离、MiniMax D07 不可外推 GLM、"
        "未结算/冲突/缺字段不能记 0、作者观点标注、标题不夸大、"
        "AI 声明、图文密度、发布日期。"
        "六图是本地 PIL 自绘静态图片：如果没有图像读取工具就不能宣称视觉审图 PASS，"
        "可审核其在稿中的文字、图注及事实约束。\n\n"
        "精确待审 SHA 索引：\n" + json.dumps(refs,ensure_ascii=False)
        + "\n\n正文：\n" + MD.read_text()
        + "\n\n证据说明：\n" + LEDGER.read_text()
        + "\n\nD07 权威工程报告原文片段：\n" + d07
    )
    body = {"new_session": True, "message": prompt,
            "model": "glm/glm-5.3", "model_change": True}
    request = Request("http://127.0.0.1:8903/api/v1/chat",
                      data=json.dumps(body,ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json"},
                      method="POST")
    outpath = ROOT / "receipts" / "20261013-daily15-review.json"
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reviewer": "LFL Web independent new session, glm/glm-5.3",
        "artifacts": refs,
        "source_sha256": sha(SOURCE),
        "status": "not_yet_started",
    }
    outpath.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urlopen(request, timeout=240) as resp:
            record.update({"http_status":resp.status,
                           "response":json.load(resp)})
        answer = record["response"].get("final_answer", "")
        # Reviewer says PASS/REVISE, but the publishing owner must still
        # confirm consistency and image visual verification before release.
        record["status"] = "review_received"
        print("REVIEW_RESULT", answer[:4500])
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        record["status"] = "review_failed"
        record["error"] = repr(exc)
        print("REVIEW_ERROR", repr(exc))
    finally:
        outpath.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n")
        print("REVIEW_RECEIPT", outpath)

if __name__ == "__main__":
    run()
