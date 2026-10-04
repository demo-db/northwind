import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { directoryOptInProblem } from './check-directory-opt-in.mjs';

const pins = JSON.parse(readFileSync(new URL('./tools.json', import.meta.url), 'utf8'));
test('both semantic tools have immutable release and per-platform archive pins', () => {
  assert.equal(pins.format, 'chinookdb-tools/1');
  for (const name of ['modelspec', 'meaninggraph']) {
    const tool = pins.tools[name];
    assert.match(tool.version, /^\d+\.\d+\.\d+$/);
    for (const platform of ['darwin_amd64', 'darwin_arm64', 'linux_amd64', 'linux_arm64']) assert.match(tool.sha256[platform], /^[a-f0-9]{64}$/);
  }
});

test('the publisher README opts into the OVDB Directory with both explicit manifest paths', () => {
  assert.equal(directoryOptInProblem('---\novdb: 1\npublish: [./ovdb.yaml, ./ovdb-database.json]\n---\n'), null);
  assert.match(directoryOptInProblem('# no frontmatter\n'), /must start with YAML frontmatter/);
  assert.match(directoryOptInProblem('---\novdb: 2\npublish: [./ovdb.yaml, ./ovdb-database.json]\n---\n'), /ovdb must be 1/);
  assert.match(directoryOptInProblem('---\novdb: 1\npublish: [./*.yaml, ./ovdb-database.json]\n---\n'), /explicit path list/);
  assert.match(directoryOptInProblem('---\novdb: 1\npublish: [./ovdb.yaml\n---\n'), /frontmatter is not valid YAML/);
  assert.match(directoryOptInProblem('---\novdb: 1\npublish: [./ovdb.yaml]\n---\n'), /must list exactly/);
  assert.match(directoryOptInProblem('---\novdb: 1\npublish: [./ovdb-database.json, ./ovdb.yaml]\n---\n'), /must list exactly/);
  assert.match(directoryOptInProblem('---\novdb: 1\npublish: [./ovdb.yaml, 1]\n---\n'), /explicit path list/);
});
