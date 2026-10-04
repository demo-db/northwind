import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const pins = JSON.parse(readFileSync(new URL('./tools.json', import.meta.url), 'utf8'));
test('both semantic tools have immutable release and per-platform archive pins', () => {
  assert.equal(pins.format, 'chinookdb-tools/1');
  for (const name of ['modelspec', 'meaninggraph']) {
    const tool = pins.tools[name];
    assert.match(tool.version, /^\d+\.\d+\.\d+$/);
    for (const platform of ['darwin_amd64', 'darwin_arm64', 'linux_amd64', 'linux_arm64']) assert.match(tool.sha256[platform], /^[a-f0-9]{64}$/);
  }
});
