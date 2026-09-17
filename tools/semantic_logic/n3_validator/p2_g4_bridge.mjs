import { createHash } from 'node:crypto';
import { SwiplEye, queryOnce } from 'eyereasoner';
import { Parser } from 'n3';

const RECEIPT_SCHEMA = 'smc.p2_g4_eye_bridge_receipt.v0.1';
const NS = 'urn:smc:p2:g4#';
const CASE = 'urn:smc:p2:g4:case';
const RESULT = 'urn:smc:p2:g4:result';

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
    ['answer_cap', 'case_ref', 'contract_valid', 'kind', 'scope_relation', 'target_present', 'stable_identity', 'coverage', 'property_observed', 'property_value', 'operator', 'expected_bool', 'observed_count', 'expected_count'],
    'request',
  );
  if (typeof value.case_ref !== 'string' || !value.case_ref) throw new Error('case_ref_required');
  if (!Number.isSafeInteger(value.answer_cap) || value.answer_cap < 1 || value.answer_cap > 256) throw new Error('answer_cap_invalid');
  if (typeof value.contract_valid !== 'boolean') throw new Error('contract_valid_invalid');
  if (!['exists', 'object_property', 'object_count'].includes(value.kind)) throw new Error('kind_invalid');
  if (!['match', 'mismatch', 'indeterminate'].includes(value.scope_relation)) throw new Error('scope_relation_invalid');
  if (!['true', 'false', 'unknown'].includes(value.target_present)) throw new Error('target_present_invalid');
  if (!['true', 'false', 'unknown'].includes(value.stable_identity)) throw new Error('stable_identity_invalid');
  if (!['complete', 'partial', 'unknown'].includes(value.coverage)) throw new Error('coverage_invalid');
  if (!['true', 'false'].includes(value.property_observed)) throw new Error('property_observed_invalid');
  if (!['true', 'false', 'unknown'].includes(value.property_value)) throw new Error('property_value_invalid');
  if (!['eq', 'ge', 'le'].includes(value.operator)) throw new Error('operator_invalid');
  if (typeof value.expected_bool !== 'boolean') throw new Error('expected_bool_invalid');
  for (const key of ['observed_count', 'expected_count']) {
    if (!Number.isSafeInteger(value[key]) || value[key] < 0) throw new Error(`${key}_invalid`);
  }
  return value;
}

function lit(value) {
  if (typeof value === 'number') return String(value);
  if (typeof value === 'boolean') return value ? '"true"' : '"false"';
  return JSON.stringify(value);
}

function dataDocument(request) {
  const rows = [];
  for (const [key, value] of Object.entries(request)) {
    if (key === 'answer_cap' || key === 'case_ref' || key === 'contract_valid') continue;
    rows.push(`<${CASE}> <${NS}${key}> ${lit(value)}.`);
  }
  return `${rows.join('\n')}\n`;
}

const RULES = `{
  <${CASE}> <${NS}scope_relation> "indeterminate".
} => {
  <${RESULT}> <${NS}predicateResult> "indeterminate".
  <${RESULT}> <${NS}predicateReason> "scope_not_observed".
}.
{
  <${CASE}> <${NS}scope_relation> "mismatch".
} => {
  <${RESULT}> <${NS}predicateResult> "indeterminate".
  <${RESULT}> <${NS}predicateReason> "target_scope_mismatch".
}.
{
  <${CASE}> <${NS}scope_relation> "match".
  <${CASE}> <${NS}kind> "exists".
  <${CASE}> <${NS}target_present> "false".
  <${CASE}> <${NS}stable_identity> "false".
} => {
  <${RESULT}> <${NS}predicateResult> "indeterminate".
  <${RESULT}> <${NS}predicateReason> "target_identity_unknown_or_identity_unstable".
}.
{
  <${CASE}> <${NS}scope_relation> "match".
  <${CASE}> <${NS}kind> "exists".
  <${CASE}> <${NS}target_present> "false".
  <${CASE}> <${NS}stable_identity> "unknown".
} => {
  <${RESULT}> <${NS}predicateResult> "indeterminate".
  <${RESULT}> <${NS}predicateReason> "target_identity_unknown_or_identity_unstable".
}.
{
  <${CASE}> <${NS}scope_relation> "match".
  <${CASE}> <${NS}kind> "exists".
  <${CASE}> <${NS}target_present> "false".
  <${CASE}> <${NS}stable_identity> "true".
  <${CASE}> <${NS}coverage> "partial".
} => {
  <${RESULT}> <${NS}predicateResult> "indeterminate".
  <${RESULT}> <${NS}predicateReason> "coverage_incomplete_for_absence".
}.
{
  <${CASE}> <${NS}scope_relation> "match".
  <${CASE}> <${NS}kind> "exists".
  <${CASE}> <${NS}target_present> "false".
  <${CASE}> <${NS}stable_identity> "true".
  <${CASE}> <${NS}coverage> "unknown".
} => {
  <${RESULT}> <${NS}predicateResult> "indeterminate".
  <${RESULT}> <${NS}predicateReason> "coverage_incomplete_for_absence".
}.
{
  <${CASE}> <${NS}scope_relation> "match".
  <${CASE}> <${NS}kind> "exists".
  <${CASE}> <${NS}target_present> "false".
  <${CASE}> <${NS}stable_identity> "true".
  <${CASE}> <${NS}coverage> "complete".
  <${CASE}> <${NS}expected_bool> "false".
} => {
  <${RESULT}> <${NS}predicateResult> "satisfied".
  <${RESULT}> <${NS}observedValue> "false".
  <${RESULT}> <${NS}coverageComplete> "true".
}.
{
  <${CASE}> <${NS}scope_relation> "match".
  <${CASE}> <${NS}kind> "exists".
  <${CASE}> <${NS}target_present> "true".
  <${CASE}> <${NS}expected_bool> "true".
} => {
  <${RESULT}> <${NS}predicateResult> "satisfied".
  <${RESULT}> <${NS}observedValue> "true".
}.
{
  <${CASE}> <${NS}scope_relation> "match".
  <${CASE}> <${NS}kind> "exists".
  <${CASE}> <${NS}target_present> "true".
  <${CASE}> <${NS}expected_bool> "false".
} => {
  <${RESULT}> <${NS}predicateResult> "unsatisfied".
  <${RESULT}> <${NS}observedValue> "true".
}.
{
  <${CASE}> <${NS}scope_relation> "match".
  <${CASE}> <${NS}kind> "object_property".
  <${CASE}> <${NS}target_present> "true".
  <${CASE}> <${NS}property_observed> "false".
} => {
  <${RESULT}> <${NS}predicateResult> "indeterminate".
  <${RESULT}> <${NS}predicateReason> "property_unobserved".
}.
{
  <${CASE}> <${NS}scope_relation> "match".
  <${CASE}> <${NS}kind> "object_count".
  <${CASE}> <${NS}coverage> "partial".
  <${CASE}> <${NS}operator> "ge".
  <${CASE}> <${NS}observed_count> ?Observed.
  <${CASE}> <${NS}expected_count> ?Expected.
  ?Observed <http://www.w3.org/2000/10/swap/math#notLessThan> ?Expected.
} => {
  <${RESULT}> <${NS}predicateResult> "satisfied".
  <${RESULT}> <${NS}predicateReason> "coverage_incomplete_but_lower_bound_is_decisive".
}.
{
  <${CASE}> <${NS}scope_relation> "match".
  <${CASE}> <${NS}kind> "object_count".
  <${CASE}> <${NS}coverage> "partial".
  <${CASE}> <${NS}operator> "le".
  <${CASE}> <${NS}observed_count> ?Observed.
  <${CASE}> <${NS}expected_count> ?Expected.
  ?Observed <http://www.w3.org/2000/10/swap/math#greaterThan> ?Expected.
} => {
  <${RESULT}> <${NS}predicateResult> "unsatisfied".
  <${RESULT}> <${NS}predicateReason> "coverage_incomplete_but_lower_bound_is_decisive".
}.
{
  <${CASE}> <${NS}scope_relation> "match".
  <${CASE}> <${NS}kind> "object_count".
  <${CASE}> <${NS}coverage> "partial".
  <${CASE}> <${NS}operator> "eq".
  <${CASE}> <${NS}observed_count> ?Observed.
  <${CASE}> <${NS}expected_count> ?Expected.
  ?Observed <http://www.w3.org/2000/10/swap/math#greaterThan> ?Expected.
} => {
  <${RESULT}> <${NS}predicateResult> "unsatisfied".
  <${RESULT}> <${NS}predicateReason> "coverage_incomplete_but_lower_bound_is_decisive".
}.
{
  <${CASE}> <${NS}scope_relation> "match".
  <${CASE}> <${NS}kind> "object_count".
  <${CASE}> <${NS}coverage> "partial".
  <${CASE}> <${NS}operator> "le".
  <${CASE}> <${NS}observed_count> ?Observed.
  <${CASE}> <${NS}expected_count> ?Expected.
  ?Observed <http://www.w3.org/2000/10/swap/math#notGreaterThan> ?Expected.
} => {
  <${RESULT}> <${NS}predicateResult> "indeterminate".
  <${RESULT}> <${NS}predicateReason> "coverage_incomplete_lower_bound_only".
}.
{
  <${CASE}> <${NS}scope_relation> "match".
  <${CASE}> <${NS}kind> "object_count".
  <${CASE}> <${NS}coverage> "partial".
  <${CASE}> <${NS}operator> "eq".
  <${CASE}> <${NS}observed_count> ?Observed.
  <${CASE}> <${NS}expected_count> ?Expected.
  ?Observed <http://www.w3.org/2000/10/swap/math#notGreaterThan> ?Expected.
} => {
  <${RESULT}> <${NS}predicateResult> "indeterminate".
  <${RESULT}> <${NS}predicateReason> "coverage_incomplete_lower_bound_only".
}.`;

const OUTPUTS = ['predicateResult', 'observedValue', 'coverageComplete', 'predicateReason'];
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
  const args = ['--nope', '--quiet', '--restricted', '--tactic', 'limited-answer', String(request.answer_cap), './data.n3', './rules.n3', '--query', './query.n3'];
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
    if (quad.object.termType !== 'Literal') throw new Error('g4_output_not_literal');
    rows.push([quad.predicate.value.slice(`${NS}query_`.length), quad.object.value]);
  }
  rows.sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
  return rows;
}

async function main() {
  try {
    const request = exactRequest(await readStdin(131_072));
    if (!request.contract_valid) {
      emit({
        schema: RECEIPT_SCHEMA,
        ok: true,
        case_ref: request.case_ref,
        validation_status: 'rejected',
        eye_args: [],
        rules_sha256: sha256Hex(RULES),
        query_sha256: sha256Hex(QUERY),
        relations: [],
      });
      return;
    }
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
    emit({schema: RECEIPT_SCHEMA, ok: false, reason: error instanceof Error ? error.message : 'p2_g4_bridge_error'}, 65);
  }
}

await main();
