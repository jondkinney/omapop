import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const bin = fileURLToPath(new URL('../bin/', import.meta.url));
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'omapop-modules-'));
function run(runtime, file, mode, options={}, text='selected') {
  const argv = runtime === 'deno' ? ['run','--quiet','--no-config','--no-prompt','--no-remote','--allow-read='+temp+','+bin] :
    ['--permission','--allow-fs-read='+temp+'/*','--allow-fs-read='+bin+'*'];
  const r=spawnSync('/usr/bin/'+runtime,[...argv,bin+'omapop-runner.mjs'],{input:JSON.stringify({mode,
    extension:{dir:temp,module:path.join(temp,file)},action:{path:[0]},input:{text},options}),encoding:'utf8',timeout:5000,maxBuffer:65536});
  assert.equal(r.status,0,r.stderr);
  const messages=r.stdout.trim().split('\n').map(JSON.parse);
  const done=messages.find(m=>m.done);assert(!done.error,JSON.stringify(done.error));
  return {messages,done};
}
try {
  fs.writeFileSync(path.join(temp,'plain.ts'),'const value: string = popclip.input.text; popclip.copyText(value); return value.toUpperCase();');
  fs.writeFileSync(path.join(temp,'module.ts'),`const opts = [{identifier:'enabled',type:'boolean',label:'<b>Enable</b>\\u202e\\x01'},
    {identifier:'prefix',type:'string',defaultValue:'default:'}] as const;
    defineExtension<Record<string, unknown>>({options:opts, actions:(input,options)=>input.text ? [{
      title: input.text, code:()=>String(options.enabled)+':'+options.prefix+input.text
    }] : []});`);
  for(const runtime of ['node','deno']) {
    const meta=run(runtime,'plain.ts','metadata');assert(!meta.messages.some(m=>m.call));
    const action=run(runtime,'plain.ts','action');assert.equal(action.done.result,'SELECTED');assert.equal(action.messages[0].call,'copyText');
    const declaration=run(runtime,'module.ts','metadata');assert.equal(declaration.done.options[0].defaultValue,true);
    assert.equal(declaration.done.options[0].label,'<b>Enable</b>');
    const populated=run(runtime,'module.ts','populate');assert.equal(populated.done.actions[0].title,'selected');
    assert.equal(run(runtime,'module.ts','action').done.result,'true:default:selected');
    assert.equal(run(runtime,'module.ts','action',{enabled:false,prefix:'custom:'}).done.result,'false:custom:selected');
    assert.deepEqual(run(runtime,'module.ts','populate',{},'').done.actions,[]);
  }
  console.log('Module adapters: Node/Deno TS returns, nested generics, passive metadata, defaults and dynamic inputs passed');
} finally {fs.rmSync(temp,{recursive:true,force:true});}
