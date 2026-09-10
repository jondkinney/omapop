// Run the production helper lifecycle handlers without touching the session bus.
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const source = readFileSync(new URL("../Service.qml", import.meta.url), "utf8");
const processBlock = source.match(/    Process \{\n        id: contextProc\n[^]*?^    \}/m)[0];
const exitHandler = processBlock.match(/onExited: function \(code, status\) \{([^]*?)\n        \}/)[1];
const timerBlock = source.match(/    Timer \{\n        id: contextRestart\n[^]*?^    \}/m)[0];
const interval = timerBlock.match(/interval: (.*)/)[1];
const trigger = timerBlock.match(/onTriggered: (.*)/)[1];
const response = source.match(/^    function onContextLine\(line\) \{[^]*?^    \}/m)[0];
const delays = [], logs = [];
let scheduled = false;
const context = vm.createContext({
  contextFailures: 0, accessibilityProbe: true, contextWaiters: {},
  contextProc: { running: false }, parseJson: JSON.parse,
  log: value => logs.push(value),
  contextRestart: { restart() {
    scheduled = true;
    delays.push(vm.runInContext(interval, context));
  } },
});
context.root = context;
vm.runInContext(response, context);
for (let attempt = 0; attempt < 8; attempt++) {
  context.contextProc.running = false;
  scheduled = false;
  vm.runInContext(exitHandler, context);
  assert.equal(scheduled, true, "an unavailable bus must not permanently disable the helper");
  vm.runInContext(trigger, context);
  assert.equal(context.contextProc.running, true);
}
assert.deepEqual(delays, [3000, 3000, 3000, 3000, 30000, 30000, 30000, 30000]);
assert.equal(logs.length, 1, "an extended outage must not flood the log");
context.onContextLine('{"id":1,"editable":false}');
assert.equal(context.contextFailures, 0, "a valid response resets the backoff");
context.contextProc.running = false;
vm.runInContext(exitHandler, context);
assert.equal(delays.at(-1), 3000);
context.accessibilityProbe = false;
scheduled = false;
vm.runInContext(exitHandler, context);
assert.equal(scheduled, false);
vm.runInContext(trigger, context);
assert.equal(context.contextProc.running, false, "disabling the probe must prevent pending restarts");
console.log("Accessibility helper recovery tests passed");
