import { writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const result = {
  schema: 'smc.n3_validator_sandbox_probe.v0.1',
  network_denied: false,
  file_write_denied: false,
  child_process_denied: false,
};

try {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 1_500);
  try {
    await fetch('https://example.com/', { signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
} catch {
  result.network_denied = true;
}

try {
  writeFileSync(process.env.SMC_PROBE_WRITE_TARGET, 'sandbox-write-should-not-succeed');
} catch {
  result.file_write_denied = true;
}

try {
  const child = spawnSync('/usr/bin/true', [], { encoding: 'utf8' });
  result.child_process_denied = Boolean(child.error) || child.status !== 0;
} catch {
  result.child_process_denied = true;
}

process.stdout.write(`${JSON.stringify(result)}\n`);
process.exitCode =
  result.network_denied && result.file_write_denied && result.child_process_denied ? 0 : 77;
