"""本地 mock GitHub raw 服务：从本地 git 仓库 git show 提供文件内容.
GET /{repo}/{commit}/{path} → git show {commit}:{path}（从 /tmp/swe_instances 或 /tmp/swe_work 找仓库）"""

import http.server
import os
import posixpath
import subprocess
import sys

REPO_DIRS = ["/tmp/swe_instances", "/tmp/swe_work"]


def find_repo(repo):
    short = repo.split("/")[-1]
    for base in REPO_DIRS:
        if not os.path.isdir(base):
            continue
        for d in os.listdir(base):
            if d.startswith(short + "_") or d == short or d.startswith(short + "-"):
                p = os.path.join(base, d)
                if os.path.isdir(os.path.join(p, ".git")):
                    return p
    return None


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parts = posixpath.normpath(self.path).strip("/").split("/")
        if len(parts) < 3:
            self.send_error(404)
            return
        repo = parts[0] + "/" + parts[1]
        commit = parts[2]
        path = "/".join(parts[3:])
        rp = find_repo(repo)
        if not rp:
            self.send_error(404, f"repo {repo} not found locally")
            return
        r = subprocess.run(
            ["git", "show", f"{commit}:{path}"], cwd=rp, capture_output=True, text=True
        )
        if r.returncode != 0:
            self.send_error(404, f"git show failed: {r.stderr[:100]}")
            return
        body = r.stdout.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
