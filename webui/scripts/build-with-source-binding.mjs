// Vite's gitignored dist must be tied to the exact tracked WebUI files used
// at build time. Otherwise a new backend HEAD may publish last week's JS/CSS.
// Only Node built-ins and the already-installed local tsc/vite are required.
import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, realpathSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const webui = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repo = resolve(webui, "..");
const dist = join(webui, "dist");
const manifestPath = join(dist, ".lfl-webui-source.json");
const schema = "lfl-webui-source/v1";
const sourceRoot = realpathSync(webui);

function fingerprint() {
  const tracked = execFileSync("git", ["-C", repo, "ls-files", "-z", "--", "webui"])
    .toString("utf8").split("\0").filter(Boolean)
    .map((relative) => Buffer.from(relative, "utf8"))
    .sort(Buffer.compare);
  if (!tracked.length) throw new Error("No Git-tracked WebUI build inputs");
  const hash = createHash("sha256");
  for (const relative of tracked) {
    const name = new TextDecoder("utf-8", { fatal: true }).decode(relative);
    const sourcePath = realpathSync(join(repo, name));
    if (!sourcePath.startsWith(sourceRoot + sep)) {
      throw new Error(`Tracked WebUI input escapes webui/: ${name}`);
    }
    hash.update(relative);
    hash.update(Buffer.from([0]));
    hash.update(createHash("sha256").update(readFileSync(sourcePath)).digest());
    hash.update(Buffer.from([0]));
  }
  return { schema, source_sha256: hash.digest("hex"), tracked_files: tracked.length };
}

const before = fingerprint();
// Remove any previous valid marker first, so an interrupted or failed build
// cannot leave a falsely qualified dist tree behind.
rmSync(manifestPath, { force: true });
for (const [bin, args] of [
  ["tsc", ["-b"]],
  ["vite", ["build"]],
]) {
  // npm run exposes node_modules/.bin in PATH; do not hardcode package
  // internals, which differ across npm/pnpm/Yarn installation layouts.
  if (bin === "vite") rmSync(dist, { recursive: true, force: true });
  const result = spawnSync(bin, args, {
    cwd: webui,
    env: process.env,
    stdio: "inherit",
  });
  if (result.error) throw new Error(`Cannot run ${bin}; run npm run build: ${result.error.message}`);
  if (result.status !== 0) process.exit(result.status || 1);
}
// Vite may change build.outDir in config. Never stamp an unrelated old dist.
if (!existsSync(join(dist, "index.html"))) {
  throw new Error("Vite did not produce dist/index.html; check build.outDir");
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
