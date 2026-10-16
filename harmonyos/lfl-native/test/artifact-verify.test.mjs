import test from 'node:test';
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';

const shimBase = new URL('./shims/', import.meta.url);
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === '@kit.NetworkKit') {
      return { url: new URL('NetworkKit.mjs', shimBase).href, shortCircuit: true };
    }
    if (specifier === '@kit.ArkTS') {
      return { url: new URL('ArkTS.mjs', shimBase).href, shortCircuit: true };
    }
    if (specifier === './StreamProtocol' && context.parentURL?.endsWith('.ts')) {
      return {
        url: new URL('../entry/src/main/ets/bridge/StreamProtocol.ts', import.meta.url).href,
        shortCircuit: true
      };
    }
    return nextResolve(specifier, context);
  }
});
const { LflTransport } = await import('../entry/src/main/ets/bridge/LflTransport.ts');
const { artifactId } = await import('../entry/src/main/ets/bridge/StreamProtocol.ts');
const { queueScenario, observed } = await import('./shims/NetworkKit.mjs');

const REF = 'artifact://v1/' + 'a'.repeat(32);

test('artifactId extracts ids and rejects malformed refs', () => {
  assert.equal(artifactId(REF), 'a'.repeat(32));
  assert.throws(() => artifactId('artifact://v1/short'), /invalid_artifact_ref/);
  assert.throws(() => artifactId('https://example.test/x'), /invalid_artifact_ref/);
});

test('verifyArtifact returns receipted sha256/size from the verified endpoint', async () => {
  queueScenario({ headers: { 'x-artifact-sha256': 'b'.repeat(64), 'x-artifact-size-bytes': '128' } });
  const v = await new LflTransport().verifyArtifact('https://example.test', 'tok', REF);
  assert.equal(v.sha256, 'b'.repeat(64));
  assert.equal(v.sizeBytes, 128);
  assert.equal(observed.at(-1).url, 'https://example.test/api/v1/artifacts/' + 'a'.repeat(32));
  assert.equal(observed.at(-1).opts.header.Authorization, 'Bearer tok');
});

test('verifyArtifact fails closed on 404 and on a bad header contract', async () => {
  queueScenario({ code: 404, body: '' });
  await assert.rejects(
    new LflTransport().verifyArtifact('https://example.test', '', REF),
    /artifact_HTTP_404/);
  queueScenario({ headers: { 'x-artifact-sha256': 'nothex', 'x-artifact-size-bytes': '5' } });
  await assert.rejects(
    new LflTransport().verifyArtifact('https://example.test', '', REF),
    /invalid_artifact_verification_headers/);
});
