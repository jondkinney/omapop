// Exercise all extension-facing HTTP APIs, through the actual restricted runner.
import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const bin = fileURLToPath(new URL('../bin/', import.meta.url));
const server = http.createServer((req,res)=>{
  if(req.url==='/large') { res.write('x'.repeat(1048577)); return; }
  res.setHeader('content-type','application/json');
  res.end(JSON.stringify({value:'ok',header:req.headers['x-test'],url:req.url}));
});
server.listen(0,'127.0.0.1');await once(server,'listening');
const base=`http://127.0.0.1:${server.address().port}`;
async function run(javascript) {
  const child=spawn('/usr/bin/deno',['run','--quiet','--no-config','--no-prompt','--no-remote','--allow-read='+bin,
    '--allow-net=127.0.0.1:'+server.address().port,bin+'omapop-runner.mjs'],{stdio:['pipe','pipe','pipe']});
  let output='',err='';
  child.stdout.on('data',c=>{output+=c;if(output.length>65536)child.kill('SIGKILL')});
  child.stderr.on('data',c=>{err=(err+c).slice(0,4096)});
  const timer=setTimeout(()=>child.kill('SIGKILL'),5000);
  child.stdin.end(JSON.stringify({extension:{dir:bin,entitlements:['network']},runtime:{allowNetwork:true},action:{javascript}}));
  const [code]=await once(child,'close');clearTimeout(timer);assert.equal(code,0,err);
  const result=output.trim().split('\n').map(JSON.parse).find(x=>x.done);assert(result);
  return result;
}
try {
  for (const expr of [
    `await (await fetch('${base}/ok')).text()`,
    `JSON.stringify((await require('axios').get('${base}/ok')).data)`,
    `await new Promise((resolve,reject)=>{const x=new XMLHttpRequest();x.open('GET','${base}/ok');x.onload=()=>resolve(x.responseText);x.onerror=reject;x.send()})`,
  ]) { const r=await run('return '+expr);assert.equal(JSON.parse(r.result).value,'ok'); }
  const merged=await run(`const a=require('axios').create({baseURL:'${base}',headers:{'x-test':'kept'},params:{a:'1'}});return JSON.stringify((await a.get('echo',{params:{b:'2'}})).data)`);
  assert.deepEqual(JSON.parse(merged.result),{value:'ok',header:'kept',url:'/echo?a=1&b=2'});
  for (const expr of [
    `await fetch('${base}/large')`,
    `await require('axios').get('${base}/large')`,
    `await new Promise((resolve,reject)=>{const x=new XMLHttpRequest();x.open('GET','${base}/large');x.onload=resolve;x.onerror=reject;x.send()})`,
  ]) { const r=await run(expr);assert.match(r.error?.message||'',/byte limit/); }
  console.log('Runner HTTP: fetch, Axios, XHR, defaults and early stream rejection passed');
} finally {server.closeAllConnections();server.close();}
