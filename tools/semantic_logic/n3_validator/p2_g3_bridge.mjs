import { createHash } from 'node:crypto';
import { SwiplEye, queryOnce } from 'eyereasoner';
import { Parser } from 'n3';

const RECEIPT_SCHEMA = 'smc.p2_g3_eye_bridge_receipt.v0.1';
const NS = 'urn:smc:p2:g3#';
const CASE = 'urn:smc:p2:g3:case';
const RESULT = 'urn:smc:p2:g3:result';
const MODES = new Set(['conflict', 'coverage', 'completeness', 'identity']);

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
  const value = exactObject(JSON.parse(raw), ['answer_cap', 'case_ref', 'mode', 'values'], 'request');
  if (typeof value.case_ref !== 'string' || !value.case_ref) throw new Error('case_ref_required');
  if (!Number.isSafeInteger(value.answer_cap) || value.answer_cap < 1 || value.answer_cap > 256) {
    throw new Error('answer_cap_out_of_range');
  }
  if (typeof value.mode !== 'string' || !MODES.has(value.mode)) throw new Error('mode_invalid');
  const fields = {
    conflict: ['dom_present', 'dom_value', 'ax_present', 'ax_value'],
    coverage: ['expected_dom', 'expected_ax', 'observed_dom', 'observed_ax', 'blind_spots_present', 'sensor_truncated'],
    completeness: ['observation_complete', 'projection_complete'],
    identity: ['mapping_status', 'candidate_count'],
  }[value.mode];
  const values = exactObject(value.values, fields, 'values');
  for (const [key, fieldValue] of Object.entries(values)) {
    if (key === 'mapping_status') {
      if (typeof fieldValue !== 'string' || !fieldValue) throw new Error(`${key}_invalid`);
    } else if (key === 'candidate_count') {
      if (!Number.isSafeInteger(fieldValue) || fieldValue < 0) throw new Error(`${key}_invalid`);
    } else if (key.endsWith('_value')) {
      if (typeof fieldValue !== 'boolean') throw new Error(`${key}_invalid`);
    } else if (typeof fieldValue !== 'boolean') {
      throw new Error(`${key}_invalid`);
    }
  }
  return { ...value, values };
}

function lit(value) {
  if (typeof value === 'boolean') return value ? '"true"' : '"false"';
  if (typeof value === 'number') return `"${value}"`;
  return JSON.stringify(value);
}

function dataDocument(request) {
  const rows = [`<${CASE}> <${NS}mode> ${lit(request.mode)}.`];
  for (const [key, value] of Object.entries(request.values)) {
    rows.push(`<${CASE}> <${NS}${key}> ${lit(value)}.`);
  }
  return `${rows.join('\n')}\n`;
}

const RULES = `{
  <${CASE}> <${NS}mode> "conflict".
  <${CASE}> <${NS}dom_present> "true".
  <${CASE}> <${NS}ax_present> "true".
  <${CASE}> <${NS}dom_value> ?D.
  <${CASE}> <${NS}ax_value> ?A.
  ?D <http://www.w3.org/2000/10/swap/log#notEqualTo> ?A.
} => {
  <${RESULT}> <${NS}canonicalValue> "null".
  <${RESULT}> <${NS}canonicalTruthState> "conflict".
  <${RESULT}> <${NS}conflictResolution> "unresolved".
}.
{
  <${CASE}> <${NS}mode> "conflict".
  <${CASE}> <${NS}dom_present> "true".
  <${CASE}> <${NS}ax_present> "true".
  <${CASE}> <${NS}dom_value> ?V.
  <${CASE}> <${NS}ax_value> ?V.
} => {
  <${RESULT}> <${NS}canonicalValue> ?V.
  <${RESULT}> <${NS}canonicalTruthState> "asserted".
  <${RESULT}> <${NS}conflictResolution> "none".
}.
{
  <${CASE}> <${NS}mode> "conflict".
  <${CASE}> <${NS}dom_present> "true".
  <${CASE}> <${NS}ax_present> "false".
  <${CASE}> <${NS}dom_value> ?V.
} => {
  <${RESULT}> <${NS}canonicalValue> ?V.
  <${RESULT}> <${NS}canonicalTruthState> "asserted".
  <${RESULT}> <${NS}conflictResolution> "none".
}.
{
  <${CASE}> <${NS}mode> "conflict".
  <${CASE}> <${NS}dom_present> "false".
  <${CASE}> <${NS}ax_present> "true".
  <${CASE}> <${NS}ax_value> ?V.
} => {
  <${RESULT}> <${NS}canonicalValue> ?V.
  <${RESULT}> <${NS}canonicalTruthState> "asserted".
  <${RESULT}> <${NS}conflictResolution> "none".
}.
{
  <${CASE}> <${NS}mode> "coverage".
  <${CASE}> <${NS}expected_dom> "true".
  <${CASE}> <${NS}expected_ax> "true".
  <${CASE}> <${NS}observed_dom> "true".
  <${CASE}> <${NS}observed_ax> "true".
  <${CASE}> <${NS}blind_spots_present> "false".
  <${CASE}> <${NS}sensor_truncated> "false".
} => {
  <${RESULT}> <${NS}coverageStatus> "complete".
  <${RESULT}> <${NS}coverageComplete> "true".
}.
{
  <${CASE}> <${NS}mode> "coverage".
  <${CASE}> <${NS}observed_dom> "true".
  <${CASE}> <${NS}observed_ax> "false".
} => {
  <${RESULT}> <${NS}coverageStatus> "partial".
  <${RESULT}> <${NS}coverageComplete> "false".
}.
{
  <${CASE}> <${NS}mode> "coverage".
  <${CASE}> <${NS}observed_dom> "false".
  <${CASE}> <${NS}observed_ax> "true".
} => {
  <${RESULT}> <${NS}coverageStatus> "partial".
  <${RESULT}> <${NS}coverageComplete> "false".
}.
{
  <${CASE}> <${NS}mode> "coverage".
  <${CASE}> <${NS}observed_dom> "true".
  <${CASE}> <${NS}observed_ax> "true".
  <${CASE}> <${NS}blind_spots_present> "true".
} => {
  <${RESULT}> <${NS}coverageStatus> "partial".
  <${RESULT}> <${NS}coverageComplete> "false".
}.
{
  <${CASE}> <${NS}mode> "coverage".
  <${CASE}> <${NS}observed_dom> "true".
  <${CASE}> <${NS}observed_ax> "true".
  <${CASE}> <${NS}sensor_truncated> "true".
} => {
  <${RESULT}> <${NS}coverageStatus> "partial".
  <${RESULT}> <${NS}coverageComplete> "false".
}.
{
  <${CASE}> <${NS}mode> "coverage".
  <${CASE}> <${NS}observed_dom> "false".
  <${CASE}> <${NS}observed_ax> "false".
} => {
  <${RESULT}> <${NS}coverageStatus> "unknown".
}.
{
  <${CASE}> <${NS}mode> "completeness".
  <${CASE}> <${NS}observation_complete> ?O.
  <${CASE}> <${NS}projection_complete> ?P.
} => {
  <${RESULT}> <${NS}observationComplete> ?O.
  <${RESULT}> <${NS}projectionComplete> ?P.
  <${RESULT}> <${NS}projectionCanUpgradeObservation> "false".
}.
{
  <${CASE}> <${NS}mode> "identity".
  <${CASE}> <${NS}mapping_status> "ambiguous".
} => {
  <${RESULT}> <${NS}identityBindingStatus> "unresolved".
  <${RESULT}> <${NS}identityFusionPerformed> "false".
  <${RESULT}> <${NS}identityReason> "ambiguous_physical_identity".
}.`;

const OUTPUTS = [
  'canonicalValue', 'canonicalTruthState', 'conflictResolution',
  'coverageStatus', 'coverageComplete',
  'observationComplete', 'projectionComplete', 'projectionCanUpgradeObservation',
  'identityBindingStatus', 'identityFusionPerformed', 'identityReason',
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
    '--nope', '--quiet', '--restricted', '--tactic', 'limited-answer', String(request.answer_cap),
    './data.n3', './rules.n3', '--query', './query.n3',
  ];
  queryOnce(Module, 'main', args);
  if (diagnostics.length !== 0) throw new Error(`eye_diagnostics:${diagnostics.join(' | ').slice(0, 512)}`);
  return { output: output.join('\n') + (output.length ? '\n' : ''), args };
}

function decode(text) {
  const parser = new Parser({ format: 'text/n3' });
  const rows = [];
  for (const quad of parser.parse(text)) {
    if (quad.subject.termType !== 'NamedNode' || quad.subject.value !== RESULT) continue;
    if (quad.predicate.termType !== 'NamedNode' || !quad.predicate.value.startsWith(`${NS}query_`)) continue;
    if (quad.object.termType !== 'Literal') throw new Error('g3_output_not_literal');
    rows.push([quad.predicate.value.slice(`${NS}query_`.length), quad.object.value]);
  }
  rows.sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
  return rows;
}

async function main() {
  try {
    const request = exactRequest(await readStdin(131_072));
    const result = await runEye(request);
    emit({
      schema: RECEIPT_SCHEMA,
      ok: true,
      case_ref: request.case_ref,
      mode: request.mode,
      eye_args: result.args,
      rules_sha256: sha256Hex(RULES),
      query_sha256: sha256Hex(QUERY),
      relations: decode(result.output),
    });
  } catch (error) {
    emit({
      schema: RECEIPT_SCHEMA,
      ok: false,
      reason: error instanceof Error ? error.message : 'p2_g3_bridge_error',
    }, 65);
  }
}

await main();
