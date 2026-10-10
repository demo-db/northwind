import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { basename, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import Ajv2020 from 'ajv/dist/2020.js';
import { parse as parseYaml } from 'yaml';
import { formatOf, formatProblem, mapItemUnderOldFormat, newFormProblems, normalisedMapping } from './lib/manifest-mapping.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const schemaPath = resolve(root, 'schemas/ovdb-database-draft-1.schema.json');
const schemaBytes = await readFile(schemaPath);
const schemaSha256 = createHash('sha256').update(schemaBytes).digest('hex');
const expectedSchemaSha256 = '2424ef00acd462ab5a8abc546fe2d1fffbbb5397e312332aedc77b3e73109488';
if (schemaSha256 !== expectedSchemaSha256) throw new Error(`OVDB database schema pin differs: ${schemaSha256}`);

const [manifestBytes, providerBytes, schemaMetadataBytes, checksumsBytes] = await Promise.all([
  readFile(resolve(root, 'manifest.json')),
  readFile(resolve(root, 'ovdb.yaml')),
  readFile(resolve(root, 'metadata/schema.json')),
  readFile(resolve(root, 'metadata/checksums.json')),
]);
const manifest = JSON.parse(manifestBytes.toString('utf8'));
const provider = parseYaml(providerBytes.toString('utf8'));
const schemaMetadata = JSON.parse(schemaMetadataBytes.toString('utf8'));
const checksums = JSON.parse(checksumsBytes.toString('utf8'));
const capabilities = manifest.capabilities?.ovdb;
const source = manifest.source;
const localId = manifest.id;
const host = manifest.siteHost;
if (!capabilities?.available || !capabilities?.canonicalUrl || !capabilities?.serverId || !capabilities?.serverDbBaseUrl || !capabilities?.connection) {
  throw new Error(`${localId}: manifest.json must declare the public OVDB identity and API routes`);
}
if (provider.id !== localId || provider.url !== capabilities.canonicalUrl) throw new Error(`${localId}: ovdb.yaml identity differs from manifest.json`);
const expectedIdentity = `https://demodb.dev/${localId}/`;
const expectedServerId = 'https://demodb.dev/ovdb';
const expectedServerDbBaseUrl = `https://demodb.dev/ovdb/db/${localId}/`;
const expectedApiUrl = `https://demodb.dev/ovdb/v1/databases/${localId}`;
if (capabilities.canonicalUrl !== expectedIdentity || capabilities.serverId !== expectedServerId || capabilities.serverDbBaseUrl !== expectedServerDbBaseUrl || capabilities.connection !== expectedApiUrl) {
  throw new Error(`${localId}: manifest.json public OVDB identity or route differs from the approved DemoDB routes`);
}
if (host !== `${localId}.demodb.dev`) throw new Error(`${localId}: siteHost must match the provider's approved DemoDB hostname`);
if (schemaMetadata.database?.id !== localId || !Array.isArray(schemaMetadata.tables)) throw new Error(`${localId}: invalid generated schema metadata`);
// The manifest is read in its own format (ovdb-manifest/draft-1 or draft-2, decision 0012 of openvaultdb/openvaultdb): an unknown
// format, a map item under draft-1, or recordset_entities beside a map item stops the generator instead of being half read.
const formatProblems = formatProblem(provider) ? [formatProblem(provider)]
  : formatOf(provider) === 'new' ? newFormProblems(provider)
    : [mapItemUnderOldFormat(provider)].filter(Boolean);
if (formatProblems.length > 0) throw new Error(`${localId}: ovdb.yaml: ${formatProblems.join('; ')}`);
if (!Array.isArray(provider.recordsets) || provider.recordsets.length === 0) throw new Error(`${localId}: ovdb.yaml must list served recordsets`);
if (provider.deployment?.discovery !== 'https://demodb.dev/.well-known/openvaultdb') throw new Error(`${localId}: deployment.discovery must point to the shared DemoDB discovery document`);
if (!provider.title || !provider.description || !provider.homepage || !provider.deployment?.engine || !provider.deployment?.url) throw new Error(`${localId}: ovdb.yaml is missing public database metadata`);

const schemaByName = new Map(schemaMetadata.tables.map((table) => [table.name, table]));
// The normalised mapping holds each recordset's own name and record type whichever form wrote them. The column mapping
// (`columns:` of draft-2) is checked by newFormProblems above and read by nothing here: the descriptor has no place for it.
const isNewForm = formatOf(provider) === 'new';
const isMap = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const entities = !isNewForm && isMap(provider.recordset_entities) ? provider.recordset_entities : {};
const recordsets = normalisedMapping(provider).map(({ name, recordType }) => {
  const table = schemaByName.get(name);
  if (!table || table.kind !== 'table') throw new Error(`${localId}: served recordset ${JSON.stringify(name)} is not a generated table`);
  const columns = table.columns.map((column) => ({
    name: column.name,
    type: column.type,
    nullable: column.nullable,
    primaryKey: column.primaryKey,
    primaryKeyPosition: column.primaryKeyPosition ?? null,
    defaultValue: column.defaultValue ?? null,
  }));
  const primaryKey = table.primaryKey ?? columns
    .filter((column) => column.primaryKey)
    .sort((a, b) => a.primaryKeyPosition - b.primaryKeyPosition)
    .map((column) => ({ column: column.name, position: column.primaryKeyPosition }));
  const foreignKeys = table.foreignKeys.map((foreignKey) => ({
    column: foreignKey.column,
    table: foreignKey.table,
    referencedColumn: foreignKey.referencedColumn,
    constraint: foreignKey.constraint,
    position: foreignKey.position,
  }));
  const recordset = {
    name,
    kind: table.kind,
    description: table.description ?? '',
    rowCount: table.rowCount ?? null,
    columns,
    primaryKey,
    foreignKeys,
  };
  // Draft-2 states the record type of every recordset. In draft-1 only recordset_entities does; a recordset it does not
  // list keeps the record type the generated schema metadata gives it.
  const modelEntity = (isNewForm || Object.hasOwn(entities, name) ? recordType : undefined) ?? table.modelEntity;
  if (modelEntity) recordset.modelEntity = modelEntity;
  return recordset;
});

const publicModelUrl = (path) => `https://${host}/model/${basename(path)}`;
const provenanceNotes = [
  source.notes ?? '',
  ...(source.path !== manifest.dataFile
    ? [`The sha256 identifies the generated fixture at ${manifest.dataFile}; recipe inputs are listed by the provider manifest.`]
    : []),
].filter(Boolean).join(' ');
const descriptor = {
  format: 'ovdb-database/draft-1',
  id: capabilities.canonicalUrl,
  localId,
  serverId: capabilities.serverId,
  serverDbBaseUrl: capabilities.serverDbBaseUrl,
  title: provider.title,
  description: provider.description,
  homepage: provider.homepage,
  apiUrl: capabilities.connection,
  capabilities: { read: capabilities.readOnly === true, query: capabilities.query === true, write: false },
  deployment: {
    engine: provider.deployment.engine,
    url: provider.deployment.url,
    discovery: provider.deployment.discovery,
  },
  model: {
    id: provider.model.address,
    url: publicModelUrl(provider.model.modelspec),
    hclUrl: publicModelUrl(provider.model.hcl),
  },
  meaning: {
    id: provider.meaning.graph.address,
    url: publicModelUrl(provider.meaning.file),
  },
  publisher: provider.publisher,
  provenance: {
    repository: source.repository,
    revision: source.revision,
    path: source.path,
    sha256: source.sha256 ?? source.databaseSha256,
    license: source.license,
    notes: provenanceNotes,
  },
  licences: provider.licences,
  recordsets,
};

const ajv = new Ajv2020({ allErrors: true, strict: true, allowUnionTypes: true });
const validate = ajv.compile(JSON.parse(schemaBytes.toString('utf8')));
if (!validate(descriptor)) throw new Error(`${localId}: invalid ovdb-database.json: ${ajv.errorsText(validate.errors)}`);

const outputPath = resolve(root, 'ovdb-database.json');
const outputBytes = Buffer.from(`${JSON.stringify(descriptor, null, 2)}\n`);
const descriptorChecksum = {
  sha256: createHash('sha256').update(outputBytes).digest('hex'),
  bytes: outputBytes.length,
};
const schemaChecksum = { sha256: schemaSha256, bytes: schemaBytes.length };
const checkOnly = process.argv.includes('--check');
if (checkOnly) {
  const currentBytes = await readFile(outputPath);
  if (!currentBytes.equals(outputBytes)) throw new Error('ovdb-database.json is stale; run pnpm generate');
  if (JSON.stringify(checksums.files['ovdb-database.json']) !== JSON.stringify(descriptorChecksum)) throw new Error('metadata/checksums.json has a stale ovdb-database.json entry');
  if (JSON.stringify(checksums.files['schemas/ovdb-database-draft-1.schema.json']) !== JSON.stringify(schemaChecksum)) throw new Error('metadata/checksums.json has a stale OVDB schema entry');
  console.log(`Validated schema and generated OVDB database descriptor for ${localId}.`);
  process.exit(0);
}
await writeFile(outputPath, outputBytes);
checksums.files['ovdb-database.json'] = descriptorChecksum;
checksums.files['schemas/ovdb-database-draft-1.schema.json'] = schemaChecksum;
checksums.files = Object.fromEntries(Object.entries(checksums.files).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0));
await writeFile(resolve(root, 'metadata/checksums.json'), `${JSON.stringify(checksums, null, 2)}\n`);
console.log(`Generated and schema-validated ovdb-database.json for ${localId} (${recordsets.length} served tables).`);
