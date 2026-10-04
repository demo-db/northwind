#!/usr/bin/env node
import { lstatSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { parse } from 'yaml';

export function directoryOptInProblem(markdown) {
  const match = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(markdown);
  if (!match) return 'must start with YAML frontmatter between --- lines';
  let metadata;
  try {
    metadata = parse(match[1], { uniqueKeys: true });
  } catch (error) {
    return `frontmatter is not valid YAML: ${error.message}`;
  }
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) return 'frontmatter must be a YAML mapping';
  if (metadata.ovdb !== 1) return 'ovdb must be 1';
  if (!Array.isArray(metadata.publish) || metadata.publish.some((entry) => typeof entry === 'string' && /[*?\[\]]/.test(entry))) {
    return 'publish entries must be an explicit path list, not a glob';
  }
  if (metadata.publish.length !== 1 || metadata.publish[0] !== './ovdb.yaml') return 'publish must list exactly [./ovdb.yaml]';
  return null;
}

const invoked = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invoked) {
  const root = dirname(dirname(fileURLToPath(import.meta.url)));
  const manifest = resolve(root, 'ovdb.yaml');
  let problem;
  try {
    if (!lstatSync(manifest).isFile()) problem = 'ovdb.yaml must be a regular file';
  } catch {
    problem = 'ovdb.yaml is missing';
  }
  if (!problem) {
    try {
      problem = directoryOptInProblem(readFileSync(resolve(root, 'OVDB.md'), 'utf8'));
    } catch {
      problem = 'OVDB.md is missing';
    }
  }
  if (problem) {
    console.error(`OVDB.md ${problem}`);
    process.exitCode = 1;
  } else {
    console.log('OVDB.md opts into the Directory and explicitly publishes ./ovdb.yaml');
  }
}
