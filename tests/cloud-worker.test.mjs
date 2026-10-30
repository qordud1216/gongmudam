import test from 'node:test';
import assert from 'node:assert/strict';
import {handle} from '../cloudflare/cloud-worker.js';

const release = 'a'.repeat(64);
const headers = {'Cf-Access-Jwt-Assertion': 'synthetic-forwarded-token'};
const response = (body, options = {}) => new Response(body, {...options,
  headers: {'X-Gongmudam-Release': release, ...options.headers}});

test('private desktop never bypasses origin signature validation', async () => {
  let called = false;
  const env = {RELEASE_ID: release, BACKEND: {fetch() {called = true; return new Response('rejected', {status: 401});}}};
  assert.equal((await handle(new Request('https://private.test/desktop/'), env)).status, 401);
  assert.equal(called, false);
  assert.equal((await handle(new Request('https://private.test/desktop/', {headers}), env)).status, 401);
  assert.equal(called, true);
});
test('matching release forwards method/body/identity and original download headers', async () => {
  const result = await handle(new Request('https://private.test/api/upload?a=1', {
    method: 'POST', headers: {...headers, Origin: 'https://private.test'}, body: 'synthetic upload'}),
  {RELEASE_ID: release, BACKEND: {async fetch(request) {
    assert.equal(request.url, 'http://127.0.0.1:8892/api/upload?a=1');
    assert.equal(await request.text(), 'synthetic upload');
    assert.equal(request.headers.get('Cf-Access-Jwt-Assertion'), headers['Cf-Access-Jwt-Assertion']);
    assert.equal(request.headers.get('Origin'), 'https://private.test');
    return response('bytes', {headers: {'Content-Disposition': 'attachment; filename=synthetic.txt'}});
  }}});
  assert.equal(result.status, 200);
  assert.equal(result.headers.get('Cache-Control'), 'no-store');
  assert.match(result.headers.get('Content-Disposition'), /synthetic.txt/);
});
test('mismatched backend release never serves private HTML or successful API data', async () => {
  const result = await handle(new Request('https://private.test/desktop/', {headers}),
    {RELEASE_ID: release, BACKEND: {fetch: () => new Response('old page', {headers: {'X-Gongmudam-Release': 'b'.repeat(64)}})}});
  assert.equal(result.status, 503);
  assert.equal((await result.json()).code, 'release_mismatch');
});
test('missing release, cross origin, excessive upload and disconnected backend fail clearly', async () => {
  const env = {RELEASE_ID: release, BACKEND: {fetch() {throw Error('offline');}}};
  assert.equal((await handle(new Request('https://private.test/', {headers}), {})).status, 503);
  assert.equal((await handle(new Request('https://private.test/api/x', {method: 'POST', headers: {...headers, Origin: 'https://other.test'}}), env)).status, 403);
  assert.equal((await handle(new Request('https://private.test/api/x', {method: 'POST', headers: {...headers, 'Content-Length': String(13 * 1024 * 1024)}}), env)).status, 413);
  const failed = await handle(new Request('https://private.test/api/x', {headers}), env);
  assert.equal((await failed.json()).code, 'origin_unavailable');
});
