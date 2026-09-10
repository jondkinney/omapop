// Exercise selection detection through the real button/action functions without
// reading the clipboard or opening a browser.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const cases = [
  ['example.com', ['openlink'], ['https://example.com']],
  ['  example.photography  ', ['openlink'], ['https://example.photography']],
  ['example.com:8443/path?x=1#section', ['openlink'], ['https://example.com:8443/path?x=1#section']],
  ['http://example.com/path', ['openlink'], ['http://example.com/path']],
  ['https://example.com?x=1', ['openlink'], ['https://example.com?x=1']],
  ['reviews of example.com', ['search', 'openlink'], ['https://example.com']],
  ['example.com example.org', ['search', 'openlink'], ['https://example.com', 'https://example.org']],
  ['ordinary words', ['search'], []],
  ['report.txt', ['search'], []],
  ['', [], []],
];
const parsed = spawnSync('/usr/bin/python3', ['-I', '-c', `
import json, runpy, sys
detect = runpy.run_path(sys.argv[1])['detect']
results = []
for text in json.load(sys.stdin):
    data, is_url = detect(text)
    results.append({'data': data, 'isUrl': is_url})
print(json.dumps(results))
`, fileURLToPath(new URL('../bin/omapop-selection.py', import.meta.url))], {
  input: JSON.stringify(cases.map(([text]) => text)), encoding: 'utf8', timeout: 5000,
});
assert.equal(parsed.status, 0, parsed.stderr);
const selections = JSON.parse(parsed.stdout);
const actions = vm.createContext({});
vm.runInContext(readFileSync(new URL('../Actions.js', import.meta.url), 'utf8').replace(/^\.pragma library\s*/, ''), actions);
const source = readFileSync(new URL('../Service.qml', import.meta.url), 'utf8');
const wanted = new Set(['stringList', 'buildInput', 'builtinButtons', 'runBuiltin']);
const functions = [...source.matchAll(/^    function (\w+)\([^]*?^    \}/gm)]
  .filter(match => wanted.has(match[1])).map(match => match[0]).join('\n');
const opened = [], copied = [];
const service = vm.createContext({
  Actions: actions, builtinGlyphs: {}, searchTemplate: actions.SEARCH_ENGINES.google,
  openUrl: url => opened.push(url), copyText: text => copied.push(text), hidePopup() {},
});
vm.runInContext(functions, service);
for (const [index, [text, expectedButtons, expectedUrls]] of cases.entries()) {
  const input = service.buildInput(text, selections[index]);
  service.current = { input, context: { canCut: false, canPaste: false } };
  const buttons = service.builtinButtons(input, service.current.context);
  assert.deepEqual(Array.from(buttons, b => b.builtin).filter(b => b !== 'copy'), expectedButtons, text);
  const link = buttons.find(b => b.builtin === 'openlink');
  if (link) {
    assert.equal(link.title, expectedUrls.length > 1 ? 'Open Links' : 'Open Link');
    opened.length = copied.length = 0;
    service.runBuiltin(link, {});
    assert.deepEqual(opened, expectedUrls, text);
    opened.length = 0;
    service.runBuiltin(link, { option: true });
    assert.deepEqual(copied, [expectedUrls.join('\n')], text);
    assert.deepEqual(opened, []);
  }
  const search = buttons.find(b => b.builtin === 'search');
  if (search) {
    opened.length = 0;
    service.runBuiltin(search, {});
    assert.equal(new URL(opened[0]).searchParams.get('q'), text);
  }
}
console.log(`${cases.length} selection/link action cases passed`);
