// Maintainer-only offline compatibility checks. Requires collected archives and
// explicit static-review decisions; never downloads, approves or signs anything.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const evidence = process.argv[2];
if (!evidence) throw new Error('Usage: node tools/check-reviewed.mjs EVIDENCE_DIRECTORY');
const decisions = JSON.parse(fs.readFileSync(path.join(root, 'catalog/review-decisions.json')));
const records = JSON.parse(fs.readFileSync(path.join(evidence, 'published-inventory.json')));
const cases = JSON.parse(fs.readFileSync(path.join(root, 'catalog/validation-cases.json')));
const A = {};
new Function('A', fs.readFileSync(path.join(root, 'Actions.js'), 'utf8').replace(/^\.pragma library\s*/, '') +
  '\nObject.assign(A,{buildUrl,urlIsOpenable,parseKeyCombo,checkRequirements,applyRegex});')(A);
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'omapop-review-'));
const env = { PATH: '/usr/bin:/bin', HOME: temp, LANG: 'C.UTF-8', TZ: 'UTC', DENO_DIR: path.join(temp, 'deno') };
const output = [];
function run(argv, input, cwd) {
  const r = spawnSync(argv[0], argv.slice(1), { input, cwd, env, encoding: 'utf8', timeout: 8000, maxBuffer: 65536 });
  if (r.error || r.status !== 0) throw new Error(String(r.error || r.stderr || `exit ${r.status}`).slice(0, 800));
  return r.stdout;
}
function runner(ext, mode, action, test, options) {
  const request = { mode, extension: ext, action, input: { text: test.text, data: test.data || { urls: [], emails: [], paths: [] }, isUrl: !!test.isUrl },
    context: { canPaste: true, canCut: true, canCopy: true, hasFormatting: false, appName: 'Editor', appIdentifier: 'code' },
    pasteboard: { text: 'Clipboard' }, options, modifiers: test.modifiers || {}, runtime: { allowNetwork: false } };
  const messages = run(['/usr/bin/deno', 'run', '--quiet', '--no-prompt', '--no-remote', '--no-config',
    '--allow-read=' + ext.dir + ',' + path.join(root, 'bin'), path.join(root, 'bin/omapop-runner.mjs')], JSON.stringify(request), ext.dir)
    .trim().split('\n').filter(Boolean).map(line => JSON.parse(line));
  const done = messages.find(x => x.done);
  if (!done || done.error) throw new Error(done?.error?.message || 'missing done');
  if (messages.some((x, i) => i > messages.indexOf(done) && x.call)) throw new Error('effects after done');
  for (const effect of messages.filter(x => x.call)) {
    assert(['pasteText','copyText','pasteboardWrite','performCommand','openUrl','pressKeys','showText','showSuccess','showFailure','print'].includes(effect.call), `unreviewed effect ${effect.call}`);
    if (effect.call === 'openUrl') assert(A.urlIsOpenable(effect.args[0]), 'blocked URL scheme');
    if (effect.call === 'pressKeys') for (const combo of effect.args[0]) assert(A.parseKeyCombo(combo, 'ctrl'), 'unparsed key');
  }
  return { done, effects: messages.filter(x => x.call && x.call !== 'print') };
}
try {
  for (const e of records.sort((a,b) => a.name.localeCompare(b.name))) {
    const d = decisions[e.shortcode];
    if (!['candidate','approved'].includes(d?.status) || d.securityReview !== 'static-reviewed') continue;
    const result = { shortcode: e.shortcode, name: e.name, sha256: e.sha256, checks: [], ok: false };
    try {
      const ext = JSON.parse(run(['/usr/bin/python3', '-I', '-c',
        'import importlib.util,json,sys; s=importlib.util.spec_from_file_location("ext",sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.catalog.verify_archive(open(sys.argv[3],"rb").read(),json.loads(sys.argv[4])); n=m.load_package(sys.argv[2],"review",[]); assert m.catalog.tree_files(sys.argv[2]) == sorted(json.loads(sys.argv[4])["files"],key=lambda x:x["path"]); print(json.dumps(n))',
        path.join(root, 'bin/omapop-extensions.py'), e.packageDir, path.join(evidence, 'packages', e.shortcode, 'package.popclipextz'), JSON.stringify(e)], '', root));
      assert(ext.usable, ext.platformNote || 'unusable package');
      let options = Object.fromEntries(ext.options.map(o => [o.identifier, o.defaultValue]));
      if (ext.module) {
        const meta = runner(ext, 'metadata', {}, { text: '' }, options);
        options = { ...Object.fromEntries(meta.done.options.map(o => [o.identifier, o.defaultValue])), ...options };
      }
      const tests = cases[e.shortcode] || [{ text: 'Hello world\nSecond line' }];
      for (const test of tests) {
        const opts = { ...options, ...test.options };
        const actions = ext.module ? runner(ext, 'populate', {}, test, opts).done.actions : ext.actions;
        function visit(list, prefix = []) {
          for (let i = 0; i < list.length; i++) {
            const action = list[i], p = [...prefix, i];
            if (action.separator) continue;
            if (test.path && JSON.stringify(p) !== JSON.stringify(test.path) && !action.submenu) continue;
            if (action.submenu) {
              const sub = Array.isArray(action.submenu) ? action.submenu : runner(ext, 'submenu', { path: p }, test, opts).done.actions;
              visit(sub, p); continue;
            }
            let check = { path: p, input: test.text, title: action.title || ext.name };
            if (action.url) {
              const url = A.buildUrl(action.url, test.text, opts, { plus: action.spacesAsPlus, clean: action.cleanQuery });
              assert(A.urlIsOpenable(url), 'blocked URL');
              assert(!/\{popclip |\*\*\*/.test(url), 'unresolved URL placeholder');
              const u = new URL(url);
              assert(['https:', 'mailto:', 'tel:', 'spotify:', 'obsidian:', 'upnote:', 'logseq:'].includes(u.protocol), 'unreviewed protocol');
              check.url = url;
              for (const option of ext.options.filter(o => o.type === 'multiple')) for (const value of option.values) {
                const variant = new URL(A.buildUrl(action.url, 'a & #/% ü', { ...opts, [option.identifier]: value }));
                assert(variant.protocol === u.protocol && !variant.username && !variant.password, 'unsafe option URL');
              }
            } else if (action.keyCombos) {
              check.keys = action.keyCombos.map(combo => A.parseKeyCombo(combo, d.commandKey === 'super' ? 'super' : 'ctrl'));
              assert(check.keys.length && check.keys.every(Boolean), 'unparsed key combo');
            } else if (action.type === 'shell') {
              assert(['s16hap','zn9dyt','2cr65p'].includes(e.shortcode), 'shell was not selected for execution review');
              const shellEnv = { ...env, POPCLIP_TEXT: test.text };
              const r = spawnSync(action.interpreter || '/usr/bin/perl', [action.shellScriptFile], { cwd: ext.dir, env: shellEnv,
                input: action.stdin === 'text' ? test.text : '', encoding: 'utf8', timeout: 5000, maxBuffer: 65536 });
              if (r.error || r.status !== 0) throw new Error(String(r.error || r.stderr));
              check.result = r.stdout;
            } else {
              const r = runner(ext, 'action', { ...action, path: p }, test, opts);
              check.result = r.done.result;
              check.effects = r.effects;
              assert(r.done.result !== null || r.effects.length > 0, 'action produced no result/effect');
            }
            if (test.expect !== undefined) {
              const actual = check.result ?? check.effects?.find(x => ['pasteText','copyText','showText','pasteboardWrite'].includes(x.call))?.args[0];
              assert.equal(actual, test.expect);
            }
            if (test.expectUrlContains) assert((check.url || check.effects?.find(x => x.call === 'openUrl')?.args[0] || '').includes(test.expectUrlContains));
            if (test.expectEffects) assert.deepEqual(check.effects.map(e => e.call), test.expectEffects);
            const value = check.result ?? check.effects?.find(x => ['pasteText','copyText','showText'].includes(x.call))?.args[0];
            if (test.validate === 'same-lines') assert.deepEqual(value.split('\n').sort(), test.text.split('\n').sort());
            if (test.validate === 'same-letters') assert.equal(value.toLowerCase().replace(/\s/g,'').split('').sort().join(''), test.text.replace(/\s/g,'').split('').sort().join(''));
            if (test.validate === 'date') assert(Number.isFinite(Date.parse(value)) && value.endsWith('Z'));
            if (test.validate === 'password') {
              assert.equal(value.length, Number(opts.leng || 16));
              if (opts.noRepeat) assert(!/(.)\1/.test(value));
              if (opts.excludeAmbiguous) assert(!/[0O1lI|]/.test(value));
              if (opts.lowercase !== false) assert(/[a-z]/.test(value));
              if (opts.uppercase !== false) assert(/[A-Z]/.test(value));
              if (opts.number !== false) assert(/[0-9]/.test(value));
              if (opts.symbol !== false) assert(/[^a-zA-Z0-9]/.test(value));
            }
            result.checks.push(check);
          }
        }
        visit(actions);
      }
      assert(result.checks.length, 'no testable actions');
      result.ok = true;
    } catch (error) { result.error = String(error.message).slice(0, 1000); }
    output.push(result);
    console.log(`${result.ok ? 'PASS' : 'FAIL'} ${e.shortcode} ${e.name}${result.error ? ': ' + result.error : ''}`);
  }
} finally { fs.rmSync(temp, { recursive: true, force: true }); }
fs.writeFileSync(path.join(evidence, 'compatibility-results.json'), JSON.stringify(output, null, 2) + '\n');
console.log(JSON.stringify({ tested: output.length, passed: output.filter(x => x.ok).length }));
process.exitCode = output.length && output.every(x => x.ok) ? 0 : 1;
