import test from 'node:test';
import assert from 'node:assert/strict';
import {handle} from '../cloudflare/worker.js';

test('root opens the B desktop at the fixed origin', async () => {
  const result = await handle(new Request('https://gongmudam.visanu81.workers.dev/'), {});
  assert.equal(result.status, 307);
  assert.equal(result.headers.get('Location'), 'https://gongmudam.visanu81.workers.dev/desktop/?variant=B');
});
test('desktop assets work independently of the PC', async () => {
  const result = await handle(new Request('https://g.test/desktop/index.html'), {ASSETS: {fetch: () => new Response('desktop')}});
  assert.equal(await result.text(), 'desktop');
});
test('API preserves query, method, body and download headers', async () => {
  let seen;
  const backend = {async fetch(request) {seen = request; assert.equal(await request.text(), 'file'); return new Response('saved', {headers: {'Content-Disposition': 'attachment; filename=test.pdf'}});}};
  const result = await handle(new Request('https://g.test/api/toolbox?a=1', {method: 'POST', headers: {Origin: 'https://g.test'}, body: 'file'}), {BACKEND: backend});
  assert.equal(seen.url, 'http://127.0.0.1:8892/api/toolbox?a=1');
  assert.equal(seen.method, 'POST');
  assert.equal(seen.headers.get('Origin'), null);
  assert.match(result.headers.get('Content-Disposition'), /test.pdf/);
});
test('cross origin writes and large uploads never reach PC', async () => {
  const backend = {fetch() {throw Error('must not fetch');}};
  assert.equal((await handle(new Request('https://g.test/api/ask', {method: 'POST', headers: {Origin: 'https://other.test'}, body: '{}'}), {BACKEND: backend})).status, 403);
  assert.equal((await handle(new Request('https://g.test/api/upload', {method: 'POST', headers: {'Content-Length': String(13 * 1024 * 1024)}}), {BACKEND: backend})).status, 413);
});
test('offline backend gives an honest retryable error', async () => {
  const result = await handle(new Request('https://g.test/api/ask'), {BACKEND: {fetch() {throw Error('offline');}}});
  assert.equal(result.status, 503);
  assert.equal((await result.json()).code, 'origin_unavailable');
});
test('backend redirects keep users on the public origin', async () => {
  const result = await handle(new Request('https://g.test/api/result'), {BACKEND: {fetch() {return new Response(null, {status: 307, headers: {Location: 'http://127.0.0.1:8892/travel.html?case=abc#settle'}});}}});
  assert.equal(result.headers.get('Location'), '/travel.html?case=abc#settle');
});
