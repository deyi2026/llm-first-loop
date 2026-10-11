import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { inspectA2aSurface, inspectA2aSdk } from '../scripts/probe-a2a-sdk.mjs';

const releaseSymbols =
  'createA2AServer TaskState AgentOperation RequestContext updateStatus addArtifact TaskArtifactParam';
const kitExport = "import { A2A } from '@hms.ai.A2A'; export { A2A };";
const manifest = JSON.stringify({apiVersion:'26', version:'26.fixture', releaseType:'Beta'});

test('missing A2A SDK declaration remains unqualified', () => {
  const result = inspectA2aSurface('', 'export { AgentController };', '', manifest);
  assert.equal(result.a2aTypesQualified, false);
  assert.equal(result.a2aDeclarationPresent, false);
  assert.ok(result.missingSymbols.includes('createA2AServer'));
});

test('API declaration without kit export is still insufficient', () => {
  const result = inspectA2aSurface(releaseSymbols, 'export { AgentController };',
    '', manifest);
  assert.equal(result.a2aTypesQualified, false);
  assert.equal(result.kitA2aExportPresent, false);
});

test('full public type surface passes only type preflight, never device qualification', () => {
  const result = inspectA2aSurface(releaseSymbols, kitExport, '', manifest);
  assert.equal(result.a2aTypesQualified, true);
  assert.deepEqual(result.missingSymbols, []);
  assert.equal(result.deviceA2aRuntime, 'not_verified_offline');
  assert.equal(result.platformA2aDispatch, 'not_verified_offline');
});

test('partial A2A declaration fails closed even if kit mentions it', () => {
  const result = inspectA2aSurface('createA2AServer TaskState', kitExport, '', manifest);
  assert.equal(result.a2aTypesQualified, false);
  assert.ok(result.missingSymbols.includes('addArtifact'));
});

test('separate OpenHarmony Release SDK is not treated as installed HMS A2A', () => {
  const root = mkdtempSync(join(tmpdir(), 'lfl-oh-release-'));
  try {
    const ets = join(root, 'ets');
    mkdirSync(join(ets, 'api'), {recursive:true});
    writeFileSync(join(ets, 'oh-uni-package.json'), JSON.stringify({
      apiVersion:'26',releaseType:'Release',version:'26.0.0.38'
    }));
    writeFileSync(join(ets, 'api', '@ohos.app.agent.AgentExtensionAbility.d.ts'),
      'declare class AgentExtensionAbility { onData(): void; }');
    const result = inspectA2aSdk(root);
    assert.equal(result.openHarmonySdkVersion, '26.0.0.38');
    assert.equal(result.openHarmonySdkReleaseType, 'Release');
    assert.equal(result.agentExtensionPresent, true);
    assert.equal(result.hmsAgentFrameworkKitInstalled, false);
    assert.equal(result.a2aDeclarationPresent, false);
    assert.equal(result.a2aTypesQualified, false);
    assert.equal(result.developerEntitlement, 'not_verified_offline');
  } finally {
    rmSync(root, {recursive:true,force:true});
  }
});
