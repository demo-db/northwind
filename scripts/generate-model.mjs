import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildChecksums, serializeChecksums } from './lib/checksums.mjs';
import { parseHcl, serializeModel, toModelspecJson, validateModel } from './lib/modelspec.mjs';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const modelDir = join(root, 'model');
const moduleInfo = { id: 'github.com/demo-db/northwind/northwind', name: 'northwind', version: '0.1.0' };
const hcl = await readFile(join(modelDir, 'northwind.modelspec.hcl'), 'utf8');
// The HCL is written by scripts/generate.py (pnpm generate runs it first), in the current ModelSpec spelling; the JSON twin is made from it, so edit the generator, not the files in model/.
const document = parseHcl(hcl);
const model = toModelspecJson(document, moduleInfo);
const problems = validateModel(model);
if (problems.length) throw new Error(problems.join('\n'));
await writeFile(join(modelDir, 'northwind.modelspec.json'), serializeModel(model));
const checksums = await buildChecksums(modelDir, { repository: 'https://github.com/demo-db/northwind', directory: 'model' }, { exclude: 'checksums.json' });
await writeFile(join(modelDir, 'checksums.json'), serializeChecksums(checksums));
console.log('Generated ModelSpec JSON and model checksums');
