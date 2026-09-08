import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = readFileSync(new URL('../Service.qml', import.meta.url), 'utf8');
const names = ['runJavascriptAction','handleRunnerCall','setExtensionEnabled','setExtensionOption','extensionPreferences','setExtensionCommandKey','installFromDirectory','populateVerifiedModule'];
const functions = [...source.matchAll(/^    function (\w+)\([^]*?^    \}/gm)].filter(m => names.includes(m[1])).map(m => m[0]).join('\n');
function harness() {
  const events = [], pending = [], writes = [];
  let spec, exit, done = 0;
  const c = vm.createContext({
    current: { input: {text:'selection'}, context: {canPaste:true,clipboardText:'plain',windowAddress:'0x123'} },
    runtimeCommand: () => ['fake-runtime'], runnerRequest: () => '{}', parseJson: JSON.parse, busyTask:null, busy:false,
    popup: {showBusy(){}}, rearm: {restart(){}}, autoHide: {restart(){}}, commandKey:'super',
    Actions: {oneLine:String,extensionCommandKey:(global,local)=>local==='ctrl'||local==='super'?local:global,
      parseKeyCombo:(text,key)=>({text,key})},
    spawn(s, cb){spec=s;exit=cb;return {cancel(){}}},
    pasteText(text,restore,cb){events.push(['paste',text]);pending.push(cb)},
    copyText(text,cb){events.push(['copy',text]);pending.push(cb)},
    performCommand(text,cb){events.push(['command',text]);pending.push(cb)},
    sendKeys(keys,target,cb){events.push(['keys',JSON.parse(JSON.stringify(keys))]);pending.push(cb)},
    openUrl(url){events.push(['url',url])}, showResult(text){events.push(['result',text])},
    showStatus(){},log(){},scriptFailed(text){events.push(['error',text])},
    extensions:[],writeSettings(value){writes.push(JSON.parse(JSON.stringify(value)))},
    extensionDownloads:false,directoryInstalling:{},directoryStatus:'',
    populatedIds:{},moduleActions:{},readGeneration:3,tagModuleAction(){},
  });
  vm.runInContext(functions, c);
  return {c,events,pending,writes,start(){c.runJavascriptAction({ext:{dir:'/tmp/example',name:'Test',commandKey:'ctrl'},action:{},path:[0]}, {},()=>done++)},
    populate(selection){c.populateVerifiedModule({dir:'/tmp/example',identifier:'example',entitlements:['dynamic']},()=>done++,selection)},
    line(msg){spec.onLine(JSON.stringify(msg))},exit(result={ok:true}){exit(result)},get done(){return done}};
}
test('paste, copy and key effects wait for prior completion; preview does not copy',()=>{
  const h=harness();h.start();
  h.line({call:'pasteText',args:['first',{}]});
  h.line({call:'copyText',args:['second',{notify:false}]});
  h.line({call:'pressKeys',args:[['command b'],{}]});
  h.line({call:'showText',args:['preview',{preview:true}]});
  h.line({done:true,result:null});
  assert.deepEqual(h.events,[]);
  h.exit();assert.deepEqual(h.events,[['paste','first']]);assert.equal(h.done,0);
  h.pending.shift()();assert.deepEqual(h.events.at(-1),['copy','second']);
  h.pending.shift()();assert.deepEqual(h.events.at(-1),['keys',[{text:'command b',key:'ctrl'}]]);
  h.pending.shift()();assert.deepEqual(h.events.at(-1),['result','preview']);assert.equal(h.done,1);
});
test('failed, truncated, excessive or stale actions perform no queued effects',()=>{
  for (const failure of ['error','truncated','overflow','stale']) {
    const h=harness();h.start();h.line({call:'pasteText',args:['must not paste',{}]});
    if(failure==='overflow') for(let i=0;i<128;i++)h.line({call:'openUrl',args:['https://example.com']});
    h.line({done:true,...(failure==='error'?{error:{message:'failed'}}:{result:null})});
    if(failure==='stale') h.c.current={};
    h.exit(failure==='truncated'?{ok:false,truncated:true}:{ok:true});
    assert(!h.events.some(e=>['paste','copy','url','keys'].includes(e[0])),failure);
  }
});
test('plain-paste transform uses captured plain clipboard before Return',()=>{
  const h=harness();h.start();h.line({call:'performCommand',args:['paste',{transform:'plain'}]});
  h.line({call:'pressKeys',args:[['return'],{}]});h.line({done:true});h.exit();
  assert.deepEqual(h.events,[['paste','plain']]);h.pending.shift()();assert.equal(h.events.at(-1)[0],'keys');
});
test('per-extension key preference preserves approval and other options',()=>{
  const h=harness();h.c.extensions=[{identifier:'first',enabled:true,usable:true,contentSha256:'a'.repeat(64),commandKey:'inherit',optionValues:{keep:'yes'}},
    {identifier:'second',enabled:false,usable:true,contentSha256:'b'.repeat(64),commandKey:'super',optionValues:{}}];
  h.c.setExtensionCommandKey('first','ctrl');
  assert.deepEqual(h.writes[0].enabled,{first:'a'.repeat(64)});
  assert.deepEqual(h.writes[0].commandKeys,{first:'ctrl',second:'super'});
  assert.equal(h.writes[0].options.first.keep,'yes');
  h.c.setExtensionCommandKey('second','inherit');assert(!('second' in h.writes[1].commandKeys));
});
test('download opt-in gate rejects install before spawning',()=>{
  const h=harness();h.c.installFromDirectory('abc123');assert.match(h.c.directoryStatus,/settings/i);
});
test('failed or stale module population never publishes actions or options',()=>{
  for(const failure of ['truncated','session','generation']) {
    const h=harness(); h.c.extensions=[{identifier:'example',options:[]}];
    h.populate({session:h.c.current,generation:h.c.readGeneration});
    h.line({done:true,actions:[{title:'stale'}],options:[{identifier:'wrong'}]});
    if(failure==='session') h.c.current={};
    if(failure==='generation') h.c.readGeneration++;
    h.exit(failure==='truncated'?{ok:false,truncated:true}:{ok:true});
    assert.equal(h.c.moduleActions.example,undefined,failure);
    assert.equal(h.c.extensions[0].options.length,0,failure);
  }
});
test('successful module population exposes declared options',()=>{
  const h=harness();h.c.extensions=[{identifier:'example',options:[{identifier:'existing'}]}];h.populate();
  h.line({done:true,actions:[{title:'current'}],options:[{identifier:'new',type:'boolean',defaultValue:true}]});h.exit();
  assert.equal(h.c.moduleActions.example[0].title,'current');
  assert.equal(h.c.extensions[0].options.length,2);
  assert.equal(h.c.extensions[0].options[1].defaultValue,true);
});
