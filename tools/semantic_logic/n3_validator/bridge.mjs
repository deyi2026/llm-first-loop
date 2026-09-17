import { createHash } from 'node:crypto';
import { SwiplEye, queryOnce } from 'eyereasoner';

const RECEIPT_SCHEMA = 'smc.eyejs_bridge_receipt.v0.1';

function sha256Hex(chunks) {
  const hash = createHash('sha256');
  for (const chunk of chunks) hash.update(chunk);
  return hash.digest('hex');
}

async function readStdin(maxBytes) {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > maxBytes) {
      throw new Error('bridge_request_too_large');
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString('utf8');
}

function exactInteger(value, label, { min, max }) {
  if (!Number.isSafeInteger(value) || value < min || value > max) {
    throw new Error(`${label}_out_of_range`);
  }
  return value;
}

function emitReceipt(receipt, exitCode = 0) {
  process.stdout.write(`${JSON.stringify(receipt)}\n`);
  process.exitCode = exitCode;
}

async function main() {
  let request;
  try {
    const raw = await readStdin(2_200_000);
    request = JSON.parse(raw);
  } catch (error) {
    emitReceipt(
      {
        schema: RECEIPT_SCHEMA,
        ok: false,
        reason: error instanceof Error ? error.message : 'invalid_bridge_request',
      },
      64,
    );
    return;
  }

  if (
    request === null ||
    typeof request !== 'object' ||
    Array.isArray(request) ||
    Object.keys(request).sort().join(',') !== 'answer_cap,max_output_bytes,n3'
  ) {
    emitReceipt({ schema: RECEIPT_SCHEMA, ok: false, reason: 'bridge_request_fields_mismatch' }, 64);
    return;
  }
  if (typeof request.n3 !== 'string') {
    emitReceipt({ schema: RECEIPT_SCHEMA, ok: false, reason: 'n3_must_be_string' }, 64);
    return;
  }

  let answerCap;
  let maxOutputBytes;
  try {
    answerCap = exactInteger(request.answer_cap, 'answer_cap', { min: 1, max: 10_000 });
    maxOutputBytes = exactInteger(request.max_output_bytes, 'max_output_bytes', {
      min: 1024,
      max: 4_000_000,
    });
  } catch (error) {
    emitReceipt(
      {
        schema: RECEIPT_SCHEMA,
        ok: false,
        reason: error instanceof Error ? error.message : 'invalid_bridge_bounds',
      },
      64,
    );
    return;
  }

  const outputChunks = [];
  const diagnosticChunks = [];
  let outputBytes = 0;
  let diagnosticBytes = 0;
  let outputExceeded = false;
  let diagnosticExceeded = false;

  function collectOutput(line) {
    const chunk = Buffer.from(`${String(line)}\n`, 'utf8');
    outputBytes += chunk.length;
    if (outputBytes <= maxOutputBytes) outputChunks.push(chunk);
    else outputExceeded = true;
  }

  function collectDiagnostic(line) {
    const chunk = Buffer.from(`${String(line)}\n`, 'utf8');
    diagnosticBytes += chunk.length;
    if (diagnosticBytes <= 131_072) diagnosticChunks.push(chunk);
    else diagnosticExceeded = true;
  }

  const eyeArgs = [
    '--nope',
    '--quiet',
    '--restricted',
    '--tactic',
    'limited-answer',
    String(answerCap),
    '--pass',
    './data.n3',
  ];

  try {
    const Module = await SwiplEye({
      print: collectOutput,
      printErr: collectDiagnostic,
      arguments: ['-q'],
    });
    Module.FS.writeFile('data.n3', request.n3);
    queryOnce(Module, 'main', eyeArgs);
  } catch (error) {
    const diagnostics = Buffer.concat(diagnosticChunks);
    emitReceipt(
      {
        schema: RECEIPT_SCHEMA,
        ok: false,
        reason: 'eye_execution_error',
        detail: error instanceof Error ? error.message.slice(0, 512) : 'unknown',
        eye_args: eyeArgs,
        output_bytes: outputBytes,
        diagnostic_bytes: diagnosticBytes,
        diagnostic_sha256: sha256Hex([diagnostics]),
      },
      65,
    );
    return;
  }

  const output = Buffer.concat(outputChunks);
  const diagnostics = Buffer.concat(diagnosticChunks);
  if (outputExceeded || diagnosticExceeded) {
    emitReceipt(
      {
        schema: RECEIPT_SCHEMA,
        ok: false,
        reason: outputExceeded ? 'output_cap_exceeded' : 'diagnostic_cap_exceeded',
        eye_args: eyeArgs,
        output_bytes: outputBytes,
        diagnostic_bytes: diagnosticBytes,
        output_sha256: sha256Hex([output]),
        diagnostic_sha256: sha256Hex([diagnostics]),
      },
      74,
    );
    return;
  }

  emitReceipt({
    schema: RECEIPT_SCHEMA,
    ok: true,
    reason: null,
    eye_args: eyeArgs,
    output_bytes: outputBytes,
    diagnostic_bytes: diagnosticBytes,
    output_sha256: sha256Hex([output]),
    diagnostic_sha256: sha256Hex([diagnostics]),
  });
}

await main();
