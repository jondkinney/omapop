import {test} from 'node:test';
import assert from 'node:assert/strict';
import api from '../ports/src/api.js';
import web from '../ports/src/web.js';
import markup from '../ports/src/markup.js';

// Success fixtures follow the primary API contracts listed in ports/README.md.
// They validate request shape and response handling; no live account mutations.
import {contracts} from './fixtures/port-api-contracts.mjs';
for(const [provider,text,options,fixture,host,path,bodyCheck] of contracts) {
  test(provider+' success contract '+(options.mode||''),async()=>{
    let calls=0;
    const result=await api.run(provider,text,options,async(url,init)=>{
      calls++;const u=new URL(url);assert.equal(u.hostname,host);assert.equal(u.pathname,path);
      assert.equal(init.redirect,'error');assert.equal(init.credentials,'omit');assert(init.signal instanceof AbortSignal);
      assert(!u.username && !u.password);
      if(provider==='pinboard') {assert.equal(u.searchParams.get('replace'),'no');assert.equal(u.searchParams.get('shared'),'no');}
      if(provider==='instapaper') assert.equal(new URLSearchParams(init.body).get('password'),' secret ');
      else if(init.body!==undefined) bodyCheck(JSON.parse(init.body));
      return new Response(typeof fixture==='string'?fixture:JSON.stringify(fixture),{status:200});
    });
    assert.equal(calls,1);assert(result.value.length);assert(['text','status','url','preview'].includes(result.kind));
    if(provider==='currency') assert.equal(result.value,'8.00 EUR (rate 2026-09-08)');
    if(provider==='webmarkdown') assert.equal(result.value,'# Heading\n\nA **word**');
  });
}
test('credential and endpoint validation occurs before network calls',async()=>{
  const denied=()=>{throw new Error('NETWORK MUST NOT RUN');};
  for(const [p,t,o] of [ ['clickup','x',{listId:'1'}],['craft','x',{endpoint:'https://evil.example/link/a/api/v1',pageId:'1',token:'private'}],
    ['slack','x',{webhook:'https://hooks.slack.com.evil.example/services/T/B/key'}],['ollama','x',{model:'x',endpoint:'http://192.168.1.1:11434'}],
    ['currency','9,3,0 USD',{}],['bitly','https://example.com/ '.repeat(6),{token:'private'}],['tana','&'.repeat(1001),{nodeId:'INBOX',token:'private'}]]) {
    await assert.rejects(api.run(p,t,o,denied),e=>!e.message.includes('NETWORK MUST NOT RUN'));
  }
});
test('HTTP errors, malformed bodies, returned URLs and secrets fail closed',async()=>{
  for(const response of [new Response('{"token":"private"}',{status:401}),new Response('not JSON'),new Response(JSON.stringify({link:'javascript:alert(1)'})),new Response(' '.repeat(131073))])
    await assert.rejects(api.run('bitly','https://example.com/',{token:'private'},async()=>response),e=>!e.message.includes('private'));
  await assert.rejects(api.run('pinboard','https://example.com/',{token:'user:private'},async(url)=>{throw new Error(url);}),e=>!e.message.includes('private'));
  await assert.rejects(api.run('wayback','https://example.com/',{},async()=>new Response(JSON.stringify({archived_snapshots:{closest:{available:true,status:'200',url:'https://evil.example/'}}}))),/unexpected URL/);
  await assert.rejects(api.run('shorten','https://example.com/',{},async()=>new Response('{"shorturl":"https://evil.example/x"}')),/unexpected host/);
});
test('batch shorteners preserve punctuation and never process more than five URLs',async()=>{
  let calls=0;
  const result=await api.run('shorten','See https://example.com/a, then https://example.com/b.',{},async()=>new Response(JSON.stringify({shorturl:'https://is.gd/'+(++calls)})));
  assert.equal(result.value,'See https://is.gd/1, then https://is.gd/2.');assert.equal(calls,2);
});
test('browser handoffs encode text fragments and enforce HTTPS providers',()=>{
  assert.equal(web.highlight('a-b & c','https://example.com/#part'),'https://example.com/#part:~:text=a%2Db%20%26%20c');
  assert.equal(web.outlook('https://outlook.office.com/mail/inbox/id/Ab%2FC%2B'), 'https://outlook.office.com/mail/deeplink/read/Ab-C-?ItemID=Ab%2FC%2B&exvsurl=1');
  assert.throws(()=>web.outlook('https://evil.example/mail/inbox/id/123'));
  for(const s of ['javascript:alert(1)','https://user:pass@example.com','https://example.com\\evil','https://example.com/\n']) assert.throws(()=>web.https(s));
  assert.throws(()=>web.urls('https://example.com/ '.repeat(11)));
  assert.equal(web.xiaohongshu('test & text'),'https://www.xiaohongshu.com/search_result?keyword=test%20%26%20text');
});
test('markup converters preserve basic formatting and escape active content',()=>{
  assert.equal(markup.markdown('<script>steal()</script><p><a href="javascript:bad()">safe</a> &amp; <a href="https://example.com/a(b)">link</a></p>'),'safe & [link](https://example.com/a%28b%29)');
  const rtf=markup.rtf('# Heading\n**bold** *italic* `code`\n{\\evil} 😀');
  assert(rtf.startsWith('{\\rtf1'));assert(rtf.includes('{\\b bold}'));assert(rtf.includes('{\\i italic}'));
  assert(rtf.includes('\\{\\\\evil\\}'));assert(rtf.includes('\\u-10179?\\u-8704?'));
  assert.throws(()=>markup.rtf('😀'.repeat(40000)));
});
