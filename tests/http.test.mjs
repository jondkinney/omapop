import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { limitedFetch, checkHttpUrl } from '../bin/omapop-http.mjs';

const server = http.createServer((req, res) => {
  if (req.url === '/exact') return res.end('x'.repeat(16));
  if (req.url === '/oversize') { res.writeHead(200, { 'content-length': '17' }); return res.end('x'.repeat(17)); }
  if (req.url === '/endless') {
    res.writeHead(200); res.write('x'.repeat(17));
    const timer = setInterval(() => res.write('x'), 1000);
    res.on('close', () => clearInterval(timer));
    return;
  }
  if (req.url === '/stall') { res.writeHead(200); res.write('x'); return; }
  if (req.url === '/foreign') { res.writeHead(302, { location: 'https://example.com/' }); return res.end(); }
  if (req.url === '/redirect') { res.writeHead(302, { location: '/exact' }); return res.end(); }
  res.end('{}');
});
server.listen(0, '127.0.0.1');
await once(server, 'listening');
const base = `http://127.0.0.1:${server.address().port}`;
try {
  const bounded = limitedFetch(fetch, () => true, { maxBytes: 16, timeoutMs: 250 });
  assert.equal(await (await bounded(base + '/exact')).text(), 'x'.repeat(16));
  assert.equal(await (await bounded(base + '/redirect')).text(), 'x'.repeat(16));
  assert.equal((await bounded(base + '/redirect', {redirect:'manual'})).status, 302);
  await assert.rejects(bounded(base + '/redirect', {redirect:'error'}), /redirect is forbidden/);
  await assert.rejects(bounded(base + '/oversize'), /byte limit/);
  const start = Date.now();
  await assert.rejects(bounded(base + '/endless'), /byte limit/);
  assert.ok(Date.now() - start < 200, 'limit+1 must abort before the total deadline');
  await assert.rejects(bounded(base + '/stall'), /deadline|abort|terminated/i);
  await assert.rejects(bounded(base + '/foreign'), /origins/);
  await assert.rejects(limitedFetch(fetch, () => false)(base), /unavailable/);
  for (const url of ['http://example.com/', 'http://example.local/', 'https://user:pass@example.com/', 'file:///etc/passwd'])
    assert.throws(() => checkHttpUrl(url));
  console.log('HTTP limits: exact, oversize, endless, stalled, redirected and denied requests passed');
} finally {
  server.closeAllConnections();
  server.close();
}
