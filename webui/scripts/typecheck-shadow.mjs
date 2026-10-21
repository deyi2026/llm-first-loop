#!/usr/bin/env node
/**
 * Shadow dual-run: tsc --noEmit vs tsrs -p tsconfig.json
 * 对比 exit code 与规范化错误集合（去 ANSI、trim、去空行、排序后比较）。
 * 每次运行追加一条记录到 webui/.typecheck-shadow.jsonl（该日志不入库，见根 .gitignore）。
 * 退出码：0 = 两边一致（无论各自是否通过）；1 = 分歧（并打印分歧行）。
 */
import { spawnSync } from 'node:child_process';
import { appendFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const LOG = join(root, '.typecheck-shadow.jsonl');
const ext = process.platform === 'win32' ? '.cmd' : '';
const bin = (n) => join(root, 'node_modules', '.bin', n + ext);

const normalize = (s) =>
  (s || '')
    .replace(/\x1b\[[0-9;]*m/g, '')
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .sort();

const run = (name, cmd, args) => {
  const t0 = Date.now();
  const r = spawnSync(cmd, args, { cwd: root, encoding: 'utf8', maxBuffer: 256 * 1024 * 1024 });
  const lines = normalize((r.stdout || '') + '\n' + (r.stderr || ''));
  return { name, code: r.status, ms: Date.now() - t0, errorCount: lines.filter((l) => /\berror TS\d+/.test(l)).length, lines };
};

const tsc = run('tsc', bin('tsc'), ['--noEmit']);
const tsrs = run('tsrs', bin('tsrs'), ['-p', 'tsconfig.json']);
const agree = tsc.code === tsrs.code && tsc.lines.join('\n') === tsrs.lines.join('\n');

const commit = spawnSync('git', ['rev-parse', '--short', 'HEAD'], { cwd: root, encoding: 'utf8' }).stdout.trim();
appendFileSync(
  LOG,
  JSON.stringify({
    ts: new Date().toISOString(),
    commit,
    agree,
    tsc: { code: tsc.code, ms: tsc.ms, errorCount: tsc.errorCount },
    tsrs: { code: tsrs.code, ms: tsrs.ms, errorCount: tsrs.errorCount },
  }) + '\n',
);

console.log(`${tsc.name}: exit=${tsc.code} errors=${tsc.errorCount} ${tsc.ms}ms`);
console.log(`${tsrs.name}: exit=${tsrs.code} errors=${tsrs.errorCount} ${tsrs.ms}ms`);
console.log(agree ? 'shadow: agree' : 'shadow: DIVERGENCE');
if (!agree) {
  const onlyTsc = tsc.lines.filter((l) => !tsrs.lines.includes(l));
  const onlyTsrs = tsrs.lines.filter((l) => !tsc.lines.includes(l));
  if (onlyTsc.length) console.log('--- only in tsc ---\n' + onlyTsc.join('\n'));
  if (onlyTsrs.length) console.log('--- only in tsrs ---\n' + onlyTsrs.join('\n'));
}
process.exit(agree ? 0 : 1);
