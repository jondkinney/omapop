// Maintainer-only tests of built port bytes. Does not download, approve or sign.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {contracts} from '../tests/fixtures/port-api-contracts.mjs';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const definitions=JSON.parse(fs.readFileSync(path.join(root,'ports/definitions.json')));
const candidates=JSON.parse(fs.readFileSync(path.join(root,'ports/candidates.json')));
const hash=raw=>crypto.createHash('sha256').update(raw).digest('hex');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'omapop-ports-'));
const env={PATH:'/usr/bin:/bin',HOME:temp,LANG:'C.UTF-8',TZ:'UTC',DENO_DIR:path.join(temp,'deno')};
const localCases={
  '7ccsap':'2+3*4','yw6cpd':'9,3 cm','phq1ch':'ab*3','6zqrwd':'item##01..03##: ##x*2##',
  '0v6xef':'0.1 0.2','29vg9p':'{"a":[1,2]}','w9pny6':'Привет Ёж',
  'g467b2':'https://outlook.office.com/mail/inbox/id/Ab%2FC%2B',
  'bqdd6c':'a-b & c','g8d8kh':'https://example.com/ https://example.org/',
  'rn4p5p':'https://example.com/','wwgbd7':'https://example.com/',
};
const A={};
new Function('A',fs.readFileSync(path.join(root,'Actions.js'),'utf8').replace(/^\.pragma library\s*/,'')+'\nObject.assign(A,{buildUrl,urlIsOpenable,parseKeyCombo});')(A);
const report={schemaVersion:1,validation:'offline Node + Deno actions; mocked API contracts and native effects',extensions:[]};
function run(argv,input='',cwd=root) {
  const r=spawnSync(argv[0],argv.slice(1),{input,cwd,env,encoding:'utf8',timeout:8000,maxBuffer:262144});
  if(r.error || r.status!==0) throw new Error(String(r.error||r.stderr||'exit '+r.status));
  return r.stdout;
}
try {
  // Run semantic, adversarial and native-helper tests before binding results to
  // archive hashes. These include request bodies and output/path/time limits.
  run(['/usr/bin/node','--test','tests/ports-local.test.mjs','tests/ports-api.test.mjs','tests/ports-host.test.mjs']);
  run(['/usr/bin/python3','-m','unittest','discover','-s','tests','-p','test_ports_native.py']);
  const checkedSources=['ports/src/local.js','ports/src/api.js','ports/src/web.js','ports/src/markup.js',
    'bin/omapop-native.py','bin/omapop-runner.mjs','bin/omapop-http.mjs','Service.qml','Popup.qml','ConfirmationText.qml','Actions.js',
    'ports/definitions.json','tools/build-ports.py','tests/ports-local.test.mjs','tests/ports-api.test.mjs','tests/ports-host.test.mjs','tests/fixtures/port-api-contracts.mjs','tests/test_ports_native.py','tools/check-ports.mjs'];
  report.sources=Object.fromEntries(checkedSources.map(f=>[f,hash(fs.readFileSync(path.join(root,f)))]));
  for(const entry of candidates) {
    const definition=definitions[entry.shortcode],record={shortcode:entry.shortcode,sha256:entry.sha256,ok:false,checks:[]};
    try {
      const dir=path.join(root,'ports/build',entry.shortcode+'.popclipext');
      const ext=JSON.parse(run(['/usr/bin/python3','-I','-c',
        'import importlib.util,json,sys; s=importlib.util.spec_from_file_location("ext",sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); e=json.loads(sys.argv[3]); m.catalog.verify_tree(sys.argv[2],e); m.catalog.verify_archive(open(sys.argv[4],"rb").read(),e); print(json.dumps(m.load_package(sys.argv[2],"review",[])))',
        path.join(root,'bin/omapop-extensions.py'),dir,JSON.stringify(entry),path.join(root,'ports/archives',entry.shortcode+'.popclipextz')]));
      assert(ext.usable,ext.platformNote);assert(!ext.module,'ports use statically declared actions');
      const defaults=Object.fromEntries(ext.options.map(o=>[o.identifier,o.defaultValue]));
      const fixtures=definition.api?contracts.filter(c=>c[0]===definition.api):[null];
      assert(fixtures.length,'API client lacks a success contract');
      for(const [index,action] of ext.actions.entries()) for(const fixture of fixtures) {
        const text=fixture?.[1]||localCases[entry.shortcode]||'Hello world\nSecond line',options={...defaults,...fixture?.[2]};
        if(action.url) {
          const url=A.buildUrl(action.url,'a & #/% ü',options);assert(A.urlIsOpenable(url));assert.equal(new URL(url).protocol,'https:');
          for(const opt of ext.options.filter(o=>o.type==='multiple')) for(const value of opt.values) {
            const u=new URL(A.buildUrl(action.url,'a & #/% ü',{...options,[opt.identifier]:value}));assert.equal(u.protocol,'https:');assert(!u.username&&!u.password);
          }
          record.checks.push({action:index,type:'url',url});continue;
        }
        if(action.keyCombos) {
          for(const key of action.keyCombos) assert(A.parseKeyCombo(key,'ctrl'));
          record.checks.push({action:index,type:'keys',keys:action.keyCombos});continue;
        }
        assert.equal(action.type,'javascript');
        // Only the test process replaces fetch. Package source is read from the
        // already-verified package tree, with real runtime permission flags.
        let prefix='';
        if(fixture) prefix=`globalThis.fetch=async(url,init)=>{const u=new URL(url);if(u.hostname!==${JSON.stringify(fixture[4])}||u.pathname!==${JSON.stringify(fixture[5])}||init.redirect!=='error'||init.credentials!=='omit')throw new Error('Unexpected request');return new Response(${JSON.stringify(typeof fixture[3]==='string'?fixture[3]:JSON.stringify(fixture[3]))},{status:200});};\n`;
        for(const runtime of ['deno','node']) {
          const request={mode:'action',extension:ext,action:{...action,javascript:prefix+action.javascript,path:[index]},
            input:{text,html:'<p>Hello <b>world</b></p>'},context:{canPaste:true,appIdentifier:'obsidian'},
            pasteboard:{text:entry.shortcode==='bqdd6c'?'https://example.com/#part':'Previous clipboard'},options,runtime:{allowNetwork:false}};
          const flags=runtime==='deno'?['run','--quiet','--no-prompt','--no-config','--no-remote','--allow-read='+dir+','+path.join(root,'bin')]
            :['--permission','--allow-fs-read='+dir+'/*','--allow-fs-read='+path.join(root,'bin')+'/*'];
          const messages=run(['/usr/bin/'+runtime,...flags,path.join(root,'bin/omapop-runner.mjs')],JSON.stringify(request),dir).trim().split('\n').map(JSON.parse);
          const done=messages.find(m=>m.done);assert(done&&!done.error,JSON.stringify(done?.error));
          const effects=messages.filter(m=>m.call);assert(done.result!==null || effects.length,'no result or effect');
          assert(!messages.slice(messages.indexOf(done)+1).some(m=>m.call),'effect after completion');
          for(const effect of effects) {
            assert(['copyText','pasteText','openUrl','showText','nativeAction','copyTypedText'].includes(effect.call));
            if(effect.call==='openUrl') assert(A.urlIsOpenable(effect.args[0]));
            if(effect.call==='nativeAction') assert(['dns','zeal','browser','speech','note','editor','print','terminal','execute'].includes(effect.args[0]));
          }
          record.checks.push({action:index,runtime,type:fixture?'mocked-api':definition.native?'native-effect':'local',result:done.result,effects});
        }
      }
      assert(record.checks.length);record.ok=true;
    } catch(error) {record.error=String(error.message).slice(0,1000);}
    report.extensions.push(record);console.log((record.ok?'PASS ':'FAIL ')+entry.shortcode+' '+entry.name+(record.error?': '+record.error:''));
  }
} finally {fs.rmSync(temp,{recursive:true,force:true});}
fs.writeFileSync(path.join(root,'catalog/port-validation.json'),JSON.stringify(report,null,2)+'\n');
const passed=report.extensions.filter(r=>r.ok).length;
console.log(JSON.stringify({tested:report.extensions.length,passed,checks:report.extensions.reduce((n,r)=>n+r.checks.length,0)}));
process.exitCode=passed===candidates.length?0:1;
