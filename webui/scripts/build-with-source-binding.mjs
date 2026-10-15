// Vite's gitignored dist must be tied to the exact tracked WebUI files used
// at build time. Otherwise a new backend HEAD may publish last week's JS/CSS.
// Only Node built-ins and the already-installed local tsc/vite are required.
import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webui = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repo = resolve(webui, "..");
const dist = join(webui, "dist");
const manifestPath = join(dist, ".lfl-webui-source.json");
const schema = "lfl-webui-source/v1";

function fingerprint() {
  const tracked = execFileSync("git", ["-C", repo, "ls-files", "-z", "--", "webui"])
    .toString("utf8").split("\0").filter(Boolean)
    .map((relative) => Buffer.from(relative, "utf8"))
    .sort(Buffer.compare);
  if (!tracked.length) throw new Error("No Git-tracked WebUI build inputs");
  const hash = createHash("sha256");
  for (const relative of tracked) {
    hash.update(relative);
    hash.update(Buffer.from([0]));
    hash.update(createHash("sha256").update(readFileSync(join(repo, relative.toString("utf8")))).digest());
    hash.update(Buffer.from([0]));
  }
  return { schema, source_sha256: hash.digest("hex"), tracked_files: tracked.length };
}

const before = fingerprint();
// Remove any previous valid marker first, so an interrupted or failed build
// cannot leave a falsely qualified dist tree behind.
rmSync(manifestPath, { force: true });
for (const [bin, args] of [
  ["typescript/bin/tsc", ["-b"]],
  ["vite/bin/vite.js", ["build"]],
]) {
  const result = spawnSync(process.execPath, [join(webui, "node_modules", bin), ...args], {
    cwd: webui,
    env: process.env,
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status || 1);
}
const after = fingerprint();
if (after.source_sha256 !== before.source_sha256 || after.tracked_files !== before.tracked_files) {
  throw new Error("WebUI tracked files changed during build; rebuild from one frozen source snapshot");
}
mkdirSync(dist, { recursive: true });
const tmp = `${manifestPath}.${process.pid}.tmp`;
writeFileSync(tmp, JSON.stringify(after) + "\n", { mode: 0o600 });
renameSync(tmp, manifestPath);
console.log(`WebUI source binding: ${after.source_sha256.slice(0, 16)} (${after.tracked_files} tracked files)`);
