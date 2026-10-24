import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../desktop/window-resize.js', import.meta.url), 'utf8');
const context = { window: {} };
vm.runInNewContext(source, context);
const { resizeGeometry } = context.window.GongmudamWindowResize;
const plain = (value) => value && Object.fromEntries(Object.entries(value));

test('each edge and corner follows the pointer direction and preserves its opposite edge', () => {
  const origin = { left: 100, top: 80, width: 300, height: 200 };
  const bounds = { width: 800, height: 600 };
  const cases = {
    N: { left: 100, top: 70, width: 300, height: 210 },
    S: { left: 100, top: 80, width: 300, height: 190 },
    E: { left: 100, top: 80, width: 280, height: 200 },
    W: { left: 80, top: 80, width: 320, height: 200 },
    NE: { left: 100, top: 70, width: 280, height: 210 },
    NW: { left: 80, top: 70, width: 320, height: 210 },
    SE: { left: 100, top: 80, width: 280, height: 190 },
    SW: { left: 80, top: 80, width: 320, height: 190 },
  };
  for (const [direction, expected] of Object.entries(cases)) {
    assert.deepEqual(plain(resizeGeometry(direction, origin, { x: -20, y: -10 }, bounds, { width: 160, height: 120 })), expected, direction);
  }
  const west = resizeGeometry('W', origin, { x: -20, y: 0 }, bounds, { width: 160, height: 120 });
  const north = resizeGeometry('N', origin, { x: 0, y: -10 }, bounds, { width: 160, height: 120 });
  assert.equal(west.left + west.width, origin.left + origin.width);
  assert.equal(north.top + north.height, origin.top + origin.height);
});

test('minimum dimensions and workspace edges clamp safely', () => {
  const bounds = { width: 500, height: 300 };
  const east = resizeGeometry('E', { left: 200, top: 20, width: 250, height: 200 }, { x: 400, y: 0 }, bounds);
  assert.deepEqual(plain(east), { left: 200, top: 20, width: 300, height: 200 });
  const west = resizeGeometry('W', { left: 200, top: 20, width: 250, height: 200 }, { x: 500, y: 0 }, bounds);
  assert.deepEqual(plain(west), { left: 130, top: 20, width: 320, height: 200 });
  const north = resizeGeometry('N', { left: 20, top: 100, width: 200, height: 160 }, { x: 0, y: 500 }, bounds);
  assert.deepEqual(plain(north), { left: 20, top: 40, width: 200, height: 220 });
  const short = resizeGeometry('SE', { left: 0, top: 0, width: 80, height: 80 }, { x: 500, y: 500 }, { width: 250, height: 180 });
  assert.deepEqual(plain(short), { left: 0, top: 0, width: 250, height: 180 });
});

test('invalid directions and non-finite geometry are rejected', () => {
  const origin = { left: 0, top: 0, width: 100, height: 100 };
  const bounds = { width: 500, height: 400 };
  assert.equal(resizeGeometry('Q', origin, { x: 0, y: 0 }, bounds), null);
  assert.equal(resizeGeometry('E', { ...origin, left: Number.NaN }, { x: 0, y: 0 }, bounds), null);
  assert.equal(resizeGeometry('S', origin, { x: 0, y: Infinity }, bounds), null);
});
