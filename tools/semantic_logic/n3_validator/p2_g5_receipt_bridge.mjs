import { createHash } from 'node:crypto';
import { SwiplEye, queryOnce } from 'eyereasoner';
import { Parser } from 'n3';

const RECEIPT_SCHEMA = 'smc.p2_g5_receipt_eye_bridge_receipt.v0.1';
const NS = 'urn:smc:p2:g5:receipt#';
const CASE = 'urn:smc:p2:g5:receipt:case';
const RESULT = 'urn:smc:p2:g5:receipt:result';

function sha256Hex(text) {
  return createHash('sha256').update(text, 'utf8').digest('hex');
}

async function readStdin(maxBytes) {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > maxBytes) throw new Error('bridge_request_too_large');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString('utf8');
}

function emit(value, code = 0) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
  process.exitCode = code;
}

function exactObject(value, fields, label) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label}_not_object`);
  }
  if (Object.keys(value).sort().join(',') !== [...fields].sort().join(',')) {
    throw new Error(`${label}_fields_mismatch`);
  }
  return value;
}

function exactRequest(raw) {
  const value = exactObject(
    JSON.parse(raw),
    [
      'answer_cap',
      'case_ref',
      'receipts',
      'reservation_result',
      'dispatch_count',
      'automatic_retry_performed',
      'provisional',
    ],
    'request',
  );
  if (typeof value.case_ref !== 'string' || !value.case_ref) throw new Error('case_ref_required');
  if (!Number.isSafeInteger(value.answer_cap) || value.answer_cap < 1 || value.answer_cap > 256) {
    throw new Error('answer_cap_invalid');
  }
  if (!Array.isArray(value.receipts) || value.receipts.length < 1 || value.receipts.length > 3) {
    throw new Error('receipts_invalid');
  }
  value.receipts = value.receipts.map((rawReceipt, index) => {
    const receipt = exactObject(
      rawReceipt,
      ['action_id', 'seq', 'status', 'history_watermark'],
      `receipt_${index}`,
    );
    if (typeof receipt.action_id !== 'string' || !receipt.action_id) throw new Error('action_id_invalid');
    if (!Number.isSafeInteger(receipt.seq) || receipt.seq < 1) throw new Error('receipt_seq_invalid');
    if (!Number.isSafeInteger(receipt.history_watermark) || receipt.history_watermark < 1) {
      throw new Error('history_watermark_invalid');
    }
    if (!['running', 'ok', 'failed', 'rejected'].includes(receipt.status)) throw new Error('receipt_status_invalid');
    return receipt;
  });
  if (typeof value.reservation_result !== 'boolean') throw new Error('reservation_result_invalid');
  if (!Number.isSafeInteger(value.dispatch_count) || value.dispatch_count < 0) throw new Error('dispatch_count_invalid');
  if (typeof value.automatic_retry_performed !== 'boolean') throw new Error('automatic_retry_invalid');
  if (typeof value.provisional !== 'boolean') throw new Error('provisional_invalid');
  return value;
}

function lit(value) {
  if (typeof value === 'boolean') return value ? '"true"' : '"false"';
  if (typeof value === 'number') return String(value);
  return JSON.stringify(value);
}

function dataDocument(request) {
  const rows = [
    `<${CASE}> <${NS}receiptCount> ${lit(request.receipts.length)}.`,
    `<${CASE}> <${NS}reservationResult> ${lit(request.reservation_result)}.`,
    `<${CASE}> <${NS}dispatchCount> ${lit(request.dispatch_count)}.`,
    `<${CASE}> <${NS}automaticRetryPerformed> ${lit(request.automatic_retry_performed)}.`,
    `<${CASE}> <${NS}provisional> ${lit(request.provisional)}.`,
  ];
  request.receipts.forEach((receipt, index) => {
    const ref = `urn:smc:p2:g5:receipt:${index}`;
    rows.push(`<${ref}> <${NS}actionId> ${lit(receipt.action_id)}.`);
    rows.push(`<${ref}> <${NS}seq> ${lit(receipt.seq)}.`);
    rows.push(`<${ref}> <${NS}status> ${lit(receipt.status)}.`);
    rows.push(`<${ref}> <${NS}historyWatermark> ${lit(receipt.history_watermark)}.`);
    if (index + 1 < request.receipts.length) {
      rows.push(`<${ref}> <${NS}next> <urn:smc:p2:g5:receipt:${index + 1}>.`);
    } else {
      rows.push(`<${CASE}> <${NS}lastReceipt> <${ref}>.`);
    }
  });
  return `${rows.join('\n')}\n`;
}

const RULES = `{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}actionId> ?Action.
  ?Right <${NS}actionId> ?Action.
  ?Left <${NS}seq> ?LeftSeq.
  ?Right <${NS}seq> ?RightSeq.
  ?RightSeq <http://www.w3.org/2000/10/swap/math#greaterThan> ?LeftSeq.
  ?Left <${NS}historyWatermark> ?LeftWatermark.
  ?Right <${NS}historyWatermark> ?RightWatermark.
  ?LeftSeq <http://www.w3.org/2000/10/swap/math#notGreaterThan> ?LeftWatermark.
  ?RightSeq <http://www.w3.org/2000/10/swap/math#notGreaterThan> ?RightWatermark.
} => {
  ?Left <${NS}pairSequenceValid> "true".
}.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}seq> ?LeftSeq.
  ?Right <${NS}seq> ?RightSeq.
  ?RightSeq <http://www.w3.org/2000/10/swap/math#notGreaterThan> ?LeftSeq.
} => {
  <${RESULT}> <${NS}sequenceViolation> "true".
}.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}actionId> ?LeftAction.
  ?Right <${NS}actionId> ?RightAction.
  ?LeftAction <http://www.w3.org/2000/10/swap/log#notEqualTo> ?RightAction.
} => {
  <${RESULT}> <${NS}sequenceViolation> "true".
}.
{
  ?Receipt <${NS}seq> ?Seq.
  ?Receipt <${NS}historyWatermark> ?Watermark.
  ?Seq <http://www.w3.org/2000/10/swap/math#greaterThan> ?Watermark.
} => {
  <${RESULT}> <${NS}sequenceViolation> "true".
}.
{
  <${CASE}> <${NS}lastReceipt> ?Receipt.
  ?Receipt <${NS}seq> ?Seq.
  ?Receipt <${NS}historyWatermark> ?Watermark.
  ?Seq <http://www.w3.org/2000/10/swap/log#notEqualTo> ?Watermark.
} => {
  <${RESULT}> <${NS}sequenceViolation> "true".
}.
{
  <${CASE}> <${NS}lastReceipt> ?Receipt.
  ?Receipt <${NS}seq> ?Seq.
  ?Receipt <${NS}historyWatermark> ?Seq.
} => {
  <${CASE}> <${NS}historyComplete> "true".
}.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "running".
  ?Right <${NS}status> "ok".
} => { ?Left <${NS}pairTransitionValid> "true". }.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "running".
  ?Right <${NS}status> "failed".
} => { ?Left <${NS}pairTransitionValid> "true". }.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "running".
  ?Right <${NS}status> "rejected".
} => { ?Left <${NS}pairTransitionValid> "true". }.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "ok".
  ?Right <${NS}status> "rejected".
} => { ?Left <${NS}pairTransitionValid> "true". }.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "failed".
  ?Right <${NS}status> "rejected".
} => { ?Left <${NS}pairTransitionValid> "true". }.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "rejected".
  ?Right <${NS}status> "rejected".
} => { ?Left <${NS}pairTransitionValid> "true". }.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "running".
  ?Right <${NS}status> "running".
} => { <${RESULT}> <${NS}transitionViolation> "true". }.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "ok".
  ?Right <${NS}status> "running".
} => { <${RESULT}> <${NS}transitionViolation> "true". }.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "ok".
  ?Right <${NS}status> "ok".
} => { <${RESULT}> <${NS}transitionViolation> "true". }.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "ok".
  ?Right <${NS}status> "failed".
} => { <${RESULT}> <${NS}transitionViolation> "true". }.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "failed".
  ?Right <${NS}status> "running".
} => { <${RESULT}> <${NS}transitionViolation> "true". }.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "failed".
  ?Right <${NS}status> "ok".
} => { <${RESULT}> <${NS}transitionViolation> "true". }.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "failed".
  ?Right <${NS}status> "failed".
} => { <${RESULT}> <${NS}transitionViolation> "true". }.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "rejected".
  ?Right <${NS}status> "running".
} => { <${RESULT}> <${NS}transitionViolation> "true". }.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "rejected".
  ?Right <${NS}status> "ok".
} => { <${RESULT}> <${NS}transitionViolation> "true". }.
{
  ?Left <${NS}next> ?Right.
  ?Left <${NS}status> "rejected".
  ?Right <${NS}status> "failed".
} => { <${RESULT}> <${NS}transitionViolation> "true". }.
{
  <${CASE}> <${NS}receiptCount> 1.
  <${CASE}> <${NS}historyComplete> "true".
} => {
  <${RESULT}> <${NS}sequenceMonotonic> "true".
  <${RESULT}> <${NS}transitionValid> "true".
}.
{
  <${CASE}> <${NS}receiptCount> 2.
  <urn:smc:p2:g5:receipt:0> <${NS}pairSequenceValid> "true".
  <${CASE}> <${NS}historyComplete> "true".
} => { <${RESULT}> <${NS}sequenceMonotonic> "true". }.
{
  <${CASE}> <${NS}receiptCount> 3.
  <urn:smc:p2:g5:receipt:0> <${NS}pairSequenceValid> "true".
  <urn:smc:p2:g5:receipt:1> <${NS}pairSequenceValid> "true".
  <${CASE}> <${NS}historyComplete> "true".
} => { <${RESULT}> <${NS}sequenceMonotonic> "true". }.
{
  <${RESULT}> <${NS}sequenceViolation> "true".
} => { <${RESULT}> <${NS}sequenceMonotonic> "false". }.
{
  <${CASE}> <${NS}receiptCount> 2.
  <urn:smc:p2:g5:receipt:0> <${NS}pairTransitionValid> "true".
} => { <${RESULT}> <${NS}transitionValid> "true". }.
{
  <${CASE}> <${NS}receiptCount> 3.
  <urn:smc:p2:g5:receipt:0> <${NS}pairTransitionValid> "true".
  <urn:smc:p2:g5:receipt:1> <${NS}pairTransitionValid> "true".
} => { <${RESULT}> <${NS}transitionValid> "true". }.
{
  <${RESULT}> <${NS}transitionViolation> "true".
} => { <${RESULT}> <${NS}transitionValid> "false". }.
{
  <${CASE}> <${NS}lastReceipt> ?Receipt.
  ?Receipt <${NS}status> ?Status.
} => { <${RESULT}> <${NS}terminalStatus> ?Status. }.
{
  <${CASE}> <${NS}dispatchCount> ?Count.
  ?Count <http://www.w3.org/2000/10/swap/math#notGreaterThan> 1.
} => { <${RESULT}> <${NS}singleDispatchPreserved> "true". }.
{
  <${CASE}> <${NS}dispatchCount> ?Count.
  ?Count <http://www.w3.org/2000/10/swap/math#greaterThan> 1.
} => {
  <${RESULT}> <${NS}singleDispatchPreserved> "false".
  <${RESULT}> <${NS}dispatchViolation> "true".
}.
{
  <${CASE}> <${NS}automaticRetryPerformed> "false".
} => { <${RESULT}> <${NS}noAutomaticRetry> "true". }.
{
  <${CASE}> <${NS}automaticRetryPerformed> "true".
} => {
  <${RESULT}> <${NS}noAutomaticRetry> "false".
  <${RESULT}> <${NS}retryViolation> "true".
}.
{
  <${CASE}> <${NS}provisional> "true".
} => { <${RESULT}> <${NS}effectEvidenceStatus> "provisional". }.
{
  <${CASE}> <${NS}provisional> "false".
} => { <${RESULT}> <${NS}effectEvidenceStatus> "non_provisional". }.
{
  <${CASE}> <${NS}reservationResult> "true".
} => { <${RESULT}> <${NS}reservationConsistent> "true". }.
{
  <${CASE}> <${NS}reservationResult> "false".
  ?Receipt <${NS}status> "rejected".
} => { <${RESULT}> <${NS}reservationConsistent> "true". }.
{
  <${RESULT}> <${NS}sequenceMonotonic> "true".
  <${RESULT}> <${NS}transitionValid> "true".
  <${RESULT}> <${NS}singleDispatchPreserved> "true".
  <${RESULT}> <${NS}noAutomaticRetry> "true".
  <${RESULT}> <${NS}reservationConsistent> "true".
} => { <${RESULT}> <${NS}invariantStatus> "ok". }.
{
  <${RESULT}> <${NS}sequenceViolation> "true".
} => { <${RESULT}> <${NS}invariantStatus> "violation". }.
{
  <${RESULT}> <${NS}transitionViolation> "true".
} => { <${RESULT}> <${NS}invariantStatus> "violation". }.
{
  <${RESULT}> <${NS}dispatchViolation> "true".
} => { <${RESULT}> <${NS}invariantStatus> "violation". }.
{
  <${RESULT}> <${NS}retryViolation> "true".
} => { <${RESULT}> <${NS}invariantStatus> "violation". }.`;

const OUTPUTS = [
  'sequenceMonotonic',
  'transitionValid',
  'terminalStatus',
  'singleDispatchPreserved',
  'noAutomaticRetry',
  'effectEvidenceStatus',
  'invariantStatus',
];
const QUERY = OUTPUTS
  .map((predicate) => `{ <${RESULT}> <${NS}${predicate}> ?V. } => { <${RESULT}> <${NS}query_${predicate}> ?V. }.`)
  .join('\n');

async function runEye(request) {
  const output = [];
  const diagnostics = [];
  const Module = await SwiplEye({
    print: (line) => output.push(String(line)),
    printErr: (line) => diagnostics.push(String(line)),
    arguments: ['-q'],
  });
  Module.FS.writeFile('data.n3', dataDocument(request));
  Module.FS.writeFile('rules.n3', RULES);
  Module.FS.writeFile('query.n3', QUERY);
  const args = [
    '--nope',
    '--quiet',
    '--restricted',
    '--tactic',
    'limited-answer',
    String(request.answer_cap),
    './data.n3',
    './rules.n3',
    '--query',
    './query.n3',
  ];
  queryOnce(Module, 'main', args);
  if (diagnostics.length !== 0) {
    throw new Error(`eye_diagnostics:${diagnostics.join(' | ').slice(0, 512)}`);
  }
  return { output: output.join('\n') + (output.length ? '\n' : ''), args };
}

function decode(text) {
  const parser = new Parser({ format: 'text/n3' });
  const quads = parser.parse(text);
  const rows = [];
  for (const quad of quads) {
    if (quad.subject.termType !== 'NamedNode' || quad.subject.value !== RESULT) continue;
    if (!quad.predicate.value.startsWith(`${NS}query_`)) continue;
    if (quad.object.termType !== 'Literal') throw new Error('g5_receipt_output_not_literal');
    rows.push([quad.predicate.value.slice(`${NS}query_`.length), quad.object.value]);
  }
  return [...new Map(rows.map((row) => [JSON.stringify(row), row])).values()].sort((left, right) =>
    JSON.stringify(left).localeCompare(JSON.stringify(right)),
  );
}

async function main() {
  try {
    const request = exactRequest(await readStdin(131_072));
    const result = await runEye(request);
    emit({
      schema: RECEIPT_SCHEMA,
      ok: true,
      case_ref: request.case_ref,
      validation_status: 'accepted',
      eye_args: result.args,
      rules_sha256: sha256Hex(RULES),
      query_sha256: sha256Hex(QUERY),
      relations: decode(result.output),
    });
  } catch (error) {
    emit(
      {
        schema: RECEIPT_SCHEMA,
        ok: false,
        reason: error instanceof Error ? error.message : 'p2_g5_receipt_bridge_error',
      },
      65,
    );
  }
}

await main();
