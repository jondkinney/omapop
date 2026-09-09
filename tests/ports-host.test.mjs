import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';
const source=fs.readFileSync(new URL('../Service.qml',import.meta.url),'utf8');
const names=['runNativeAction','copyTypedText','handleConfirm','hidePopup','finishAction','handleRunnerCall'];
const code=[...source.matchAll(/^    function (\w+)\([^]*?^    \}/gm)].filter(m=>names.includes(m[1])).map(m=>m[0]).join('\n');
function harness() {
  const calls=[],results=[],prompts=[];
  const s=vm.createContext({current:{input:{text:'echo "selected"'},context:{}},busyTask:null,busy:false,nativeHelper:'/native.py',clipboardHelper:'/clipboard.py',pendingConfirm:null,
    popup:{visible:true,showBusy(){},showConfirm(...args){prompts.push(args)},dismiss(){this.visible=false},keyboardMode:false},
    spawn(spec,callback){calls.push({spec,callback});return {cancel(){}}},parseJson:JSON.parse,
    showResult(message){results.push(message)},scriptFailed(message){s.current.failed=true;results.push(message)},
    Actions:{oneLine:(s,n)=>s.slice(0,n)},cancelSelection(){},luaCall(){},rearm:{restart(){}},
  });
  vm.runInContext(code,s);return {s,calls,results,prompts};
}
const allowed={ext:{entitlements:['native']},action:{}};
test('print and script execution cannot spawn until their concrete confirmation is accepted',()=>{
  for(const kind of ['print','execute']) {
    const h=harness();let done=0;
    h.s.runNativeAction(kind,{printer:'office'},allowed,()=>done++);
    assert.equal(h.calls.length,0);assert.equal(h.prompts.length,1);assert.equal(done,0);
    assert.equal(h.prompts[0][2],h.s.current.input.text);
    h.s.handleConfirm(true);assert.equal(h.calls.length,1);
    const spec=h.calls[0].spec;assert.deepEqual(Array.from(spec.command),['/usr/bin/python3','-I','/native.py']);
    assert.equal(JSON.parse(spec.stdin).text,'echo "selected"');
    h.calls[0].callback({ok:true,stdout:'{"ok":true,"message":"Completed"}'});
    assert.equal(done,1);h.s.finishAction(allowed);assert(h.s.popup.visible,'result must remain visible');
  }
});
test('declined, dismissed, stale or unentitled native requests perform no work',()=>{
  for(const mode of ['decline','dismiss','stale','permission']) {
    const h=harness();
    h.s.runNativeAction('execute',{},mode==='permission'?{ext:{entitlements:[]}}:allowed,()=>{});
    if(mode==='decline') h.s.handleConfirm(false);
    if(mode==='dismiss') {h.s.hidePopup();h.s.handleConfirm(true);}
    if(mode==='stale') {h.s.current={};h.s.handleConfirm(true);}
    assert.equal(h.calls.length,0,mode);
  }
});
test('native failures and typed clipboard writes fail closed',()=>{
  const h=harness();
  h.s.runNativeAction('dns',{},allowed,()=>{});h.calls[0].callback({ok:true,stdout:'{"ok":false,"error":"Unavailable"}'});
  assert(h.s.current.failed);
  const before=h.calls.length;
  h.s.copyTypedText('data','application/x-shellscript',()=>{});assert.equal(h.calls.length,before);
  h.s.copyTypedText('{\\rtf1 hi}','text/rtf',()=>{});
  assert.deepEqual(Array.from(h.calls.at(-1).spec.command).slice(-2),['--type','text/rtf']);
});
test('an explicit text preview survives action completion',()=>{
  const h=harness();h.s.handleRunnerCall('showText',['answer',{preview:true}],allowed,()=>{});
  h.s.finishAction(allowed);assert(h.s.popup.visible);assert.equal(h.s.current.lastResult,'answer');
});
