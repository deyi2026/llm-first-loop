// Read-only installed SDK probe. No network, account access, installs or signing.
import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

function readText(path) {
  return existsSync(path) ? readFileSync(path, 'utf8') : '';
}

export function inspectA2aSdk(input) {
  const root = resolve(input);
  // DevEco may bundle the HMS and OpenHarmony components in a default SDK
  // tree. An OpenHarmony 26 Release downloaded to user Library is a SEPARATE
  // component and must never be represented as HMS A2A support.
  const hmsEts = join(root, 'hms', 'ets');
  const sdkOhEts = join(root, 'openharmony', 'ets');
  const userOhEts = join(root, 'ets');
  const openEts = existsSync(join(sdkOhEts, 'api')) ? sdkOhEts :
    (existsSync(join(userOhEts, 'oh-uni-package.json')) ? userOhEts : '');
  const manifestText = readText(join(hmsEts, 'uni-package.json'));
  const api = readText(join(hmsEts, 'api', '@hms.ai.A2A.d.ts'));
  const kit = readText(join(hmsEts, 'kits', '@kit.AgentFrameworkKit.d.ts'));
  const ability = openEts ? readText(join(openEts, 'api',
    '@ohos.app.agent.AgentExtensionAbility.d.ts')) : '';
  const report = inspectA2aSurface(api, kit, ability, manifestText);
  let openManifest = {};
  try {
    openManifest = JSON.parse(openEts ?
      readText(join(openEts, 'oh-uni-package.json')) || '{}' : '{}');
  } catch {
    openManifest = {};
  }
  return {
    ...report,
    hmsAgentFrameworkKitInstalled: kit.length > 0,
    openHarmonySdkVersion: openManifest.version ?? null,
    openHarmonySdkReleaseType: openManifest.releaseType ?? null,
    openHarmonySdkApi: openManifest.apiVersion ?? null,
    abilityKitAgentExtensionQualifiedByTypes: ability.includes('class AgentExtensionAbility')
  };
}

export function inspectA2aSurface(api, kit, ability, manifestText) {
  let manifest = {};
  try { manifest = JSON.parse(manifestText || '{}'); } catch { manifest = {}; }
  const required = [
    'createA2AServer', 'TaskState', 'AgentOperation',
    'RequestContext', 'updateStatus', 'addArtifact', 'TaskArtifactParam'
  ];
  const missingSymbols = required.filter(name => !api.includes(name));
  const a2aDeclarationPresent = api.length > 0;
  const kitA2aExportPresent = kit.includes('A2A') && kit.includes('@hms.ai.A2A');
  return {
    sdkVersion: manifest.version ?? null,
    sdkApi: manifest.apiVersion ?? null,
    sdkReleaseType: manifest.releaseType ?? null,
    a2aDeclarationPresent,
    kitA2aExportPresent,
    missingSymbols,
    agentExtensionPresent: ability.includes('class AgentExtensionAbility'),
    a2aTypesQualified: a2aDeclarationPresent && kitA2aExportPresent &&
      missingSymbols.length === 0,
    developerEntitlement: 'not_verified_offline',
    deviceA2aRuntime: 'not_verified_offline',
    platformA2aDispatch: 'not_verified_offline'
  };
}

if (process.argv[1]?.endsWith('probe-a2a-sdk.mjs')) {
  const sdkRoot = process.argv[2];
  if (!sdkRoot) {
    process.stderr.write(
      'usage: node probe-a2a-sdk.mjs <sdk-default-root-or-OpenHarmony-version-root>\n');
    process.exitCode = 2;
  } else {
    const report = inspectA2aSdk(sdkRoot);
    process.stdout.write(JSON.stringify(report, null, 2) + '\n');
    process.exitCode = report.a2aTypesQualified ? 0 : 2;
  }
}
