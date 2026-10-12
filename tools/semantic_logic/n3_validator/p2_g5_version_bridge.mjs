import { createHash } from 'node:crypto';
import { SwiplEye, queryOnce } from 'eyereasoner';
import { Parser } from 'n3';

const RECEIPT_SCHEMA = 'smc.p2_g5_version_eye_bridge_receipt.v0.1';
const NS = 'urn:smc:p2:g5:version#';
const CASE = 'urn:smc:p2:g5:version:case';
const RESULT = 'urn:smc:p2:g5:version:result';

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
      'version_scope',
      'expected_availability',
      'observed_availability',
      'scope_relation',
      'identity_stable',
      'version_equal',
      'page_same',
      'document_same',
      'target_present',
      'coverage_complete',
      'object_changed',
      'resource_changed',
    ],
    'request',
  );
  if (typeof value.case_ref !== 'string' || !value.case_ref) throw new Error('case_ref_required');
  if (!Number.isSafeInteger(value.answer_cap) || value.answer_cap < 1 || value.answer_cap > 256) {
    throw new Error('answer_cap_invalid');
  }
  if (!['object', 'resource', 'snapshot'].includes(value.version_scope)) throw new Error('version_scope_invalid');
  if (!['available', 'expired', 'unavailable', 'unauthorized'].includes(value.expected_availability)) {
    throw new Error('expected_availability_invalid');
  }
  if (!['available', 'expired', 'unavailable', 'unauthorized'].includes(value.observed_availability)) {
    throw new Error('observed_availability_invalid');
  }
  if (!['match', 'mismatch', 'indeterminate'].includes(value.scope_relation)) throw new Error('scope_relation_invalid');
  for (const key of [
    'identity_stable',
    'version_equal',
    'page_same',
    'document_same',
    'target_present',
    'coverage_complete',
    'object_changed',
    'resource_changed',
  ]) {
    if (typeof value[key] !== 'boolean') throw new Error(`${key}_invalid`);
  }
  return value;
}

function lit(value) {
  if (typeof value === 'boolean') return value ? '"true"' : '"false"';
  return JSON.stringify(value);
}

function dataDocument(request) {
  const rows = [];
  for (const [key, value] of Object.entries(request)) {
    if (key === 'answer_cap') continue;
    rows.push(`<${CASE}> <${NS}${key}> ${lit(value)}.`);
  }
  return `${rows.join('\n')}\n`;
}

const BASE = `
  <${CASE}> <${NS}expected_availability> "available".
  <${CASE}> <${NS}observed_availability> "available".`;
const MATCH = `${BASE}
  <${CASE}> <${NS}scope_relation> "match".`;
const DISTINCT = `${MATCH}
  <${CASE}> <${NS}version_equal> "false".`;
const SAME_LINEAGE = `${DISTINCT}
  <${CASE}> <${NS}page_same> "true".
  <${CASE}> <${NS}document_same> "true".`;

const RULES = `{
  <${CASE}> <${NS}expected_availability> "expired".
} => {
  <${RESULT}> <${NS}versionResult> "indeterminate".
  <${RESULT}> <${NS}versionReason> "expected_version_expired".
}.
{
  <${CASE}> <${NS}expected_availability> "unavailable".
} => {
  <${RESULT}> <${NS}versionResult> "indeterminate".
  <${RESULT}> <${NS}versionReason> "expected_version_unavailable".
}.
{
  <${CASE}> <${NS}expected_availability> "unauthorized".
} => {
  <${RESULT}> <${NS}versionResult> "indeterminate".
  <${RESULT}> <${NS}versionReason> "expected_version_unauthorized".
}.
{
  <${CASE}> <${NS}expected_availability> "available".
  <${CASE}> <${NS}observed_availability> "expired".
} => {
  <${RESULT}> <${NS}versionResult> "indeterminate".
  <${RESULT}> <${NS}versionReason> "observed_version_expired".
}.
{
  <${CASE}> <${NS}expected_availability> "available".
  <${CASE}> <${NS}observed_availability> "unavailable".
} => {
  <${RESULT}> <${NS}versionResult> "indeterminate".
  <${RESULT}> <${NS}versionReason> "observed_version_unavailable".
}.
{
  <${CASE}> <${NS}expected_availability> "available".
  <${CASE}> <${NS}observed_availability> "unauthorized".
} => {
  <${RESULT}> <${NS}versionResult> "indeterminate".
  <${RESULT}> <${NS}versionReason> "observed_version_unauthorized".
}.
{
  ${BASE}
  <${CASE}> <${NS}scope_relation> "indeterminate".
} => {
  <${RESULT}> <${NS}versionResult> "indeterminate".
  <${RESULT}> <${NS}versionReason> "scope_not_observed".
}.
{
  ${BASE}
  <${CASE}> <${NS}scope_relation> "mismatch".
} => {
  <${RESULT}> <${NS}versionResult> "indeterminate".
  <${RESULT}> <${NS}versionReason> "target_scope_mismatch".
}.
{
  ${MATCH}
  <${CASE}> <${NS}version_scope> "object".
  <${CASE}> <${NS}identity_stable> "false".
} => {
  <${RESULT}> <${NS}versionResult> "indeterminate".
  <${RESULT}> <${NS}versionReason> "target_identity_unstable".
}.
{
  ${MATCH}
  <${CASE}> <${NS}version_scope> "object".
  <${CASE}> <${NS}identity_stable> "true".
  <${CASE}> <${NS}version_equal> "true".
} => {
  <${RESULT}> <${NS}versionResult> "match".
  <${RESULT}> <${NS}versionReason> "exact_version".
  <${RESULT}> <${NS}versionComparable> "true".
}.
{
  ${MATCH}
  <${CASE}> <${NS}version_scope> "resource".
  <${CASE}> <${NS}version_equal> "true".
} => {
  <${RESULT}> <${NS}versionResult> "match".
  <${RESULT}> <${NS}versionReason> "exact_version".
  <${RESULT}> <${NS}versionComparable> "true".
}.
{
  ${MATCH}
  <${CASE}> <${NS}version_scope> "snapshot".
  <${CASE}> <${NS}version_equal> "true".
} => {
  <${RESULT}> <${NS}versionResult> "match".
  <${RESULT}> <${NS}versionReason> "exact_version".
  <${RESULT}> <${NS}versionComparable> "true".
}.
{
  ${DISTINCT}
  <${CASE}> <${NS}version_scope> "object".
  <${CASE}> <${NS}identity_stable> "true".
  <${CASE}> <${NS}page_same> "false".
} => {
  <${RESULT}> <${NS}versionResult> "stale".
  <${RESULT}> <${NS}versionReason> "page_generation_changed".
  <${RESULT}> <${NS}versionComparable> "false".
}.
{
  ${DISTINCT}
  <${CASE}> <${NS}version_scope> "resource".
  <${CASE}> <${NS}page_same> "false".
} => {
  <${RESULT}> <${NS}versionResult> "stale".
  <${RESULT}> <${NS}versionReason> "page_generation_changed".
  <${RESULT}> <${NS}versionComparable> "false".
}.
{
  ${DISTINCT}
  <${CASE}> <${NS}version_scope> "snapshot".
  <${CASE}> <${NS}page_same> "false".
} => {
  <${RESULT}> <${NS}versionResult> "stale".
  <${RESULT}> <${NS}versionReason> "page_generation_changed".
  <${RESULT}> <${NS}versionComparable> "false".
}.
{
  ${DISTINCT}
  <${CASE}> <${NS}version_scope> "object".
  <${CASE}> <${NS}identity_stable> "true".
  <${CASE}> <${NS}page_same> "true".
  <${CASE}> <${NS}document_same> "false".
} => {
  <${RESULT}> <${NS}versionResult> "stale".
  <${RESULT}> <${NS}versionReason> "document_generation_changed".
  <${RESULT}> <${NS}versionComparable> "false".
}.
{
  ${DISTINCT}
  <${CASE}> <${NS}version_scope> "resource".
  <${CASE}> <${NS}page_same> "true".
  <${CASE}> <${NS}document_same> "false".
} => {
  <${RESULT}> <${NS}versionResult> "stale".
  <${RESULT}> <${NS}versionReason> "document_generation_changed".
  <${RESULT}> <${NS}versionComparable> "false".
}.
{
  ${DISTINCT}
  <${CASE}> <${NS}version_scope> "snapshot".
  <${CASE}> <${NS}page_same> "true".
  <${CASE}> <${NS}document_same> "false".
} => {
  <${RESULT}> <${NS}versionResult> "stale".
  <${RESULT}> <${NS}versionReason> "document_generation_changed".
  <${RESULT}> <${NS}versionComparable> "false".
}.
{
  ${SAME_LINEAGE}
  <${CASE}> <${NS}version_scope> "object".
  <${CASE}> <${NS}identity_stable> "true".
  <${CASE}> <${NS}target_present> "false".
  <${CASE}> <${NS}coverage_complete> "false".
} => {
  <${RESULT}> <${NS}versionResult> "indeterminate".
  <${RESULT}> <${NS}versionReason> "target_not_observed_incomplete".
  <${RESULT}> <${NS}versionComparable> "true".
}.
{
  ${SAME_LINEAGE}
  <${CASE}> <${NS}version_scope> "object".
  <${CASE}> <${NS}identity_stable> "true".
  <${CASE}> <${NS}target_present> "false".
  <${CASE}> <${NS}coverage_complete> "true".
} => {
  <${RESULT}> <${NS}versionResult> "stale".
  <${RESULT}> <${NS}versionReason> "target_absent_in_observed_version".
  <${RESULT}> <${NS}versionComparable> "true".
}.
{
  ${SAME_LINEAGE}
  <${CASE}> <${NS}version_scope> "object".
  <${CASE}> <${NS}identity_stable> "true".
  <${CASE}> <${NS}target_present> "true".
  <${CASE}> <${NS}object_changed> "true".
} => {
  <${RESULT}> <${NS}versionResult> "stale".
  <${RESULT}> <${NS}versionReason> "object_changed_same_generation".
  <${RESULT}> <${NS}versionComparable> "true".
}.
{
  ${SAME_LINEAGE}
  <${CASE}> <${NS}version_scope> "object".
  <${CASE}> <${NS}identity_stable> "true".
  <${CASE}> <${NS}target_present> "true".
  <${CASE}> <${NS}object_changed> "false".
} => {
  <${RESULT}> <${NS}versionResult> "match".
  <${RESULT}> <${NS}versionReason> "object_unchanged_new_observation".
  <${RESULT}> <${NS}versionComparable> "true".
}.
{
  ${SAME_LINEAGE}
  <${CASE}> <${NS}version_scope> "resource".
  <${CASE}> <${NS}resource_changed> "true".
} => {
  <${RESULT}> <${NS}versionResult> "stale".
  <${RESULT}> <${NS}versionReason> "resource_changed_same_generation".
  <${RESULT}> <${NS}versionComparable> "true".
}.
{
  ${SAME_LINEAGE}
  <${CASE}> <${NS}version_scope> "resource".
  <${CASE}> <${NS}resource_changed> "false".
} => {
  <${RESULT}> <${NS}versionResult> "match".
  <${RESULT}> <${NS}versionReason> "resource_unchanged_new_observation".
  <${RESULT}> <${NS}versionComparable> "true".
}.
{
  ${SAME_LINEAGE}
  <${CASE}> <${NS}version_scope> "snapshot".
} => {
  <${RESULT}> <${NS}versionResult> "stale".
  <${RESULT}> <${NS}versionReason> "different_snapshot_same_generation".
  <${RESULT}> <${NS}versionComparable> "true".
}.
{
  <${CASE}> <${NS}version_scope> ?Scope.
} => {
  <${RESULT}> <${NS}automaticRefreshPerformed> "false".
  <${RESULT}> <${NS}silentRebindPerformed> "false".
}.`;

const OUTPUTS = [
  'versionResult',
  'versionReason',
  'versionComparable',
  'automaticRefreshPerformed',
  'silentRebindPerformed',
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
    if (quad.object.termType !== 'Literal') throw new Error('g5_version_output_not_literal');
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
        reason: error instanceof Error ? error.message : 'p2_g5_version_bridge_error',
      },
      65,
    );
  }
}

await main();
