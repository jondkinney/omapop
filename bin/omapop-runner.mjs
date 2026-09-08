// Omapop JavaScript runner: executes extension JavaScript actions and modules
// out of process, under Deno (preferred) or Node.
//
// Protocol: one JSON request on stdin; JSON lines on stdout. Each line is either
//   {"call": "<api method>", "args": [...]}         an effect for the shell to perform
//   {"done": true, "result": string|null}          the action finished
//   {"done": true, "actions": [...]}               populate/submenu finished
//   {"done": true, "error": {"message", "kind"}}   kind: error | settings | signin
// The shell performs every effect (paste, copy, open URL, key presses, UI) so
// extension code never touches the compositor, the clipboard or the network
// beyond what its entitlements allow. The runtime's own sandbox flags (Deno
// --allow-read/--allow-net, Node --permission) are set by the shell.

import { limitedFetch, checkHttpUrl } from "./omapop-http.mjs";

const isDeno = typeof globalThis.Deno !== "undefined";
const nativeFetch = globalThis.fetch.bind(globalThis);
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const MAX_INPUT = 8 * 1024 * 1024;
const MAX_EMIT = 2 * 1024 * 1024;

let nodeFs = null;
let nodeProcess = null;
let nodeCrypto = null;
if (!isDeno) {
  nodeFs = await import("node:fs");
  nodeProcess = (await import("node:process")).default;
}
try {
  nodeCrypto = await import("node:crypto");
} catch (e) {
  nodeCrypto = null;
}

function writeOut(text) {
  const bytes = encoder.encode(text);
  if (isDeno) {
    let offset = 0;
    while (offset < bytes.length) offset += Deno.stdout.writeSync(bytes.subarray(offset));
  } else {
    nodeFs.writeSync(1, bytes);
  }
}

function emit(obj) {
  let line = JSON.stringify(obj);
  if (line.length > MAX_EMIT) {
    line = JSON.stringify({ done: true, error: { message: "runner output exceeded " + MAX_EMIT + " bytes", kind: "error" } });
  }
  writeOut(line + "\n");
}

async function readStdin() {
  const chunks = [];
  let total = 0;
  if (isDeno) {
    const buf = new Uint8Array(65536);
    while (true) {
      const n = await Deno.stdin.read(buf);
      if (n === null) break;
      total += n;
      if (total > MAX_INPUT) throw new Error("request too large");
      chunks.push(buf.slice(0, n));
    }
  } else {
    for await (const chunk of nodeProcess.stdin) {
      total += chunk.length;
      if (total > MAX_INPUT) throw new Error("request too large");
      chunks.push(new Uint8Array(chunk));
    }
  }
  const all = new Uint8Array(total);
  let offset = 0;
  for (const c of chunks) { all.set(c, offset); offset += c.length; }
  return decoder.decode(all);
}

function readTextFile(path) {
  if (isDeno) return Deno.readTextFileSync(path);
  return nodeFs.readFileSync(path, "utf8");
}

function fileExists(path) {
  try {
    if (isDeno) return Deno.statSync(path).isFile;
    return nodeFs.statSync(path).isFile();
  } catch (e) {
    return false;
  }
}

function dirname(path) {
  const i = path.lastIndexOf("/");
  return i <= 0 ? "/" : path.slice(0, i);
}

function joinPath(base, rel) {
  const parts = (base + "/" + rel).split("/");
  const out = [];
  for (const p of parts) {
    if (p === "" || p === ".") continue;
    if (p === "..") { out.pop(); continue; }
    out.push(p);
  }
  return "/" + out.join("/");
}

function insidePackage(path, root) {
  return path === root || path.startsWith(root.endsWith("/") ? root : root + "/");
}

// ---------------------------------------------------------------- request

const request = JSON.parse(await readStdin());
const mode = request.mode || "action";
const ext = request.extension || {};
const packageRoot = String(ext.dir || "/nonexistent");
const allowNetwork = !!(request.runtime && request.runtime.allowNetwork);
const entitlements = Array.isArray(ext.entitlements) ? ext.entitlements : [];
const populating = mode !== "action";
globalThis.fetch = limitedFetch(nativeFetch, () => allowNetwork && !populating);

let finished = false;
function finish(obj) {
  if (finished) return;
  finished = true;
  emit(Object.assign({ done: true }, obj));
}

function classifyError(err) {
  const message = err && err.message !== undefined ? String(err.message) : String(err);
  const lower = message.toLowerCase();
  let kind = "error";
  if (err && err.omapopKind) kind = err.omapopKind;
  else if (lower.startsWith("settings error")) kind = "settings";
  else if (lower.startsWith("not signed in")) kind = "signin";
  return { message: message.slice(0, 2000), kind };
}

// ---------------------------------------------------------------- extension API

function call(name, ...args) {
  if (populating) throw new Error(API_NAME + "." + name + " cannot be called while populating actions");
  emit({ call: name, args });
  return Promise.resolve();
}

const modifiers = Object.freeze(Object.assign({ shift: false, control: false, option: false, command: false }, populating ? {} : (request.modifiers || {})));
let options = Object.freeze(Object.assign({}, request.options || {}));
const context = Object.freeze(Object.assign({
  hasFormatting: false, canPaste: true, canCopy: true, canCut: true,
  browserUrl: "", browserTitle: "", appName: "", appIdentifier: "",
}, request.context || {}));
const rawInput = request.input || {};
const data = Object.assign({ urls: [], nonHttpUrls: [], emails: [], paths: [] }, rawInput.data || {});
const input = Object.freeze({
  text: String(rawInput.text || ""),
  matchedText: String(rawInput.matchedText !== undefined ? rawInput.matchedText : (rawInput.text || "")),
  regexResult: rawInput.regexResult || null,
  html: rawInput.html || "",
  xhtml: rawInput.html || "",
  markdown: rawInput.markdown || String(rawInput.text || ""),
  rtf: "",
  data: Object.freeze(data),
  content: Object.freeze({ "public.utf8-plain-text": String(rawInput.text || ""), "public.html": rawInput.html || undefined }),
  isUrl: !!rawInput.isUrl,
});

let pasteboardText = String((request.pasteboard && request.pasteboard.text) || "");
const pasteboard = {
  get text() { return pasteboardText; },
  set text(value) { pasteboardText = String(value); call("pasteboardWrite", pasteboardText); },
  get content() { return { "public.utf8-plain-text": pasteboardText }; },
  set content(value) {
    const text = value && (value["public.utf8-plain-text"] || value["public.html"]) || "";
    pasteboardText = String(text);
    call("pasteboardWrite", pasteboardText);
  },
};

const MODIFIER_SHIFT = 131072, MODIFIER_CONTROL = 262144, MODIFIER_OPTION = 524288, MODIFIER_COMMAND = 1048576;

function modifierNames(mask) {
  const names = [];
  if (mask & MODIFIER_SHIFT) names.push("shift");
  if (mask & MODIFIER_CONTROL) names.push("control");
  if (mask & MODIFIER_OPTION) names.push("option");
  if (mask & MODIFIER_COMMAND) names.push("command");
  return names;
}

function optionsWithAuth() {
  return new Proxy(options, {
    get(target, prop) {
      if (prop === "authsecret") {
        const v = target.authsecret;
        if (v === undefined || v === "") {
          const err = new Error("Not signed in");
          err.omapopKind = "signin";
          throw err;
        }
      }
      return target[prop];
    },
  });
}

// The global object the extension format exposes to scripts.
const API_NAME = "popclip";
const api = {
  get input() { return input; },
  get context() { return context; },
  get modifiers() { return modifiers; },
  get options() { return optionsWithAuth(); },
  pasteText(text, opts) { return call("pasteText", String(text), { restore: !!(opts && opts.restore) }); },
  pasteContent(content, opts) {
    const text = content && (content["public.utf8-plain-text"] || content["public.html"]) || "";
    return call("pasteText", String(text), { restore: !!(opts && opts.restore) });
  },
  copyText(text, opts) { return call("copyText", String(text), { notify: !(opts && opts.notify === false) }); },
  copyContent(content, opts) {
    const text = content && (content["public.utf8-plain-text"] || content["public.html"]) || "";
    return call("copyText", String(text), { notify: !(opts && opts.notify === false) });
  },
  performCommand(command, opts) { return call("performCommand", String(command), { transform: (opts && opts.transform) || "none" }); },
  showText(text, opts) { return call("showText", String(text), { style: (opts && opts.style) || "compact", preview: !!(opts && opts.preview) }); },
  showSuccess() { return call("showSuccess"); },
  showFailure() { return call("showFailure"); },
  showSettings() { return call("showSettings"); },
  appear() { return call("appear"); },
  settingsRequiredError(message) { const e = new Error(message || "Settings error"); e.omapopKind = "settings"; return e; },
  signInRequiredError(message) { const e = new Error(message || "Not signed in"); e.omapopKind = "signin"; return e; },
  pressKey(key, mods, opts) {
    const name = typeof key === "number" ? "0x" + key.toString(16) : String(key);
    const spec = typeof mods === "number" && mods ? modifierNames(mods).join(" ") + " " + name : name;
    return call("pressKeys", [spec], { target: (opts && opts.target) || "session" });
  },
  pressKeys(sequence, opts) { return call("pressKeys", (Array.isArray(sequence) ? sequence : [sequence]).map(k => typeof k === "number" ? "0x" + k.toString(16) : String(k)), { target: (opts && opts.target) || "session" }); },
  openUrl(url, opts) { return call("openUrl", String(url), Object.assign({ activate: true, backgroundTab: false }, opts || {})); },
  openTemplateUrl(template, query, opts) {
    opts = opts || {};
    let q = String(query === undefined ? input.matchedText : query).trim();
    if (opts.clean) q = q.replace(/[\n\t]+/g, " ").replace(/ {2,}/g, " ");
    const verbatim = opts.verbatim === undefined ? modifiers.option : !!opts.verbatim;
    if (verbatim) q = '"' + q + '"';
    let encoded = encodeURIComponent(q);
    if (opts.plus) encoded = encoded.replace(/%20/g, "+");
    let url = String(template).replace(/\*\*\*/g, encoded).replace(/\{popclip text\}/gi, encoded);
    const optionValues = Object.assign({}, options, opts.options || {});
    url = url.replace(/\{popclip option ([^}]+)\}/gi, (m, id) => encodeURIComponent(String(optionValues[id.trim()] === undefined ? "" : optionValues[id.trim()])));
    if (opts.copy) call("copyText", q, { notify: false });
    return call("openUrl", url, { activate: opts.activate !== false, backgroundTab: !!opts.backgroundTab });
  },
  revealFile(path) { return call("revealFile", String(path)); },
  runShortcut() { return Promise.reject(new Error("macOS Shortcuts are not available on Linux")); },
  performService() { return Promise.reject(new Error("macOS Services are not available on Linux")); },
  runAppleScript() { return Promise.reject(new Error("AppleScript is not available on Linux")); },
  runAppleScriptFile() { return Promise.reject(new Error("AppleScript is not available on Linux")); },
  share() { return Promise.reject(new Error("macOS sharing is not available on Linux")); },
  runShellScript(source, opts) {
    if (!entitlements.includes("script")) return Promise.reject(new Error("runShellScript needs the script entitlement"));
    return new Promise((resolve, reject) => {
      pendingShell.push({ resolve, reject });
      emit({ call: "runShellScript", args: [String(source), Object.assign({ shellMode: "none" }, opts || {})], id: pendingShell.length - 1 });
      reject(new Error("runShellScript is not supported by this runner yet"));
    });
  },
  runShellScriptFile() { return Promise.reject(new Error("runShellScriptFile is not supported by this runner yet")); },
};
const pendingShell = [];

// ---------------------------------------------------------------- util

function toBytes(data) {
  if (data instanceof Uint8Array) return data;
  return encoder.encode(String(data));
}

function base64Encode(data, opts) {
  const bytes = toBytes(data);
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  let out = btoa(bin);
  if (opts && opts.urlSafe) out = out.replace(/\+/g, "-").replace(/\//g, "_");
  if (opts && opts.trimmed) out = out.replace(/=+$/, "");
  return out;
}

function base64Decode(text, opts) {
  let s = String(text).replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  const bin = atob(s);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return opts && opts.bytes ? bytes : decoder.decode(bytes);
}

function digest(alg, data, key) {
  if (!nodeCrypto) throw new Error("hashing is unavailable in this runtime");
  const name = String(alg).toLowerCase();
  const h = key === undefined ? nodeCrypto.createHash(name) : nodeCrypto.createHmac(name, toBytes(key));
  h.update(toBytes(data));
  return new Uint8Array(h.digest());
}

function stripTags(html) {
  return String(html).replace(/<script[\s\S]*?<\/script>/gi, "").replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<br\s*\/?>/gi, "\n").replace(/<\/(p|div|li|h[1-6]|tr)>/gi, "\n").replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'");
}

function randomUniform(max) {
  if (!Number.isSafeInteger(max) || max < 0 || max > 0xffffffff)
    throw new RangeError("max must be a non-negative 32-bit integer");
  const bound = max + 1;
  const minimum = 0x100000000 % bound;
  const sample = new Uint32Array(1);
  do { crypto.getRandomValues(sample); } while (sample[0] < minimum);
  return sample[0] % bound;
}

const util = {
  localize: (s) => String(s),
  hasDictionaryDefinition: () => false,
  getDictionaryDefinition: () => undefined,
  getSpellingLanguages: () => [],
  getPreferredSpellingLanguages: () => [],
  checkSpelling: () => true,
  getSpellingGuesses: () => [],
  get localeInfo() {
    const locale = (Intl.DateTimeFormat().resolvedOptions().locale) || "en-US";
    const parts = locale.split("-");
    return { localeIdentifier: locale.replace("-", "_"), regionCode: parts[1] || "", languageCode: parts[0] || "en", decimalSeparator: ".", groupingSeparator: ",", currencyCode: "", currencySymbol: "" };
  },
  get timeZoneInfo() {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    return { identifier: tz, abbreviation: tz, secondsOffset: -new Date().getTimezoneOffset() * 60, daylightSaving: false };
  },
  htmlToMarkdown: (html) => stripTags(html).trim(),
  cleanHtml: (html) => String(html).replace(/<script[\s\S]*?<\/script>/gi, "").replace(/<style[\s\S]*?<\/style>/gi, "").replace(/\son\w+="[^"]*"/gi, ""),
  base64Encode,
  base64Decode,
  buildQuery: (params) => Object.entries(params || {}).map(([k, v]) => encodeURIComponent(k) + "=" + encodeURIComponent(String(v))).join("&"),
  parseQuery: (query) => { const out = {}; for (const [k, v] of new URLSearchParams(String(query))) out[k] = v; return out; },
  clarify: (obscured) => JSON.parse(base64Decode(String(obscured).replace(/[a-zA-Z]/g, (c) => String.fromCharCode((c <= "Z" ? 90 : 122) >= (c = c.charCodeAt(0) + 13) ? c : c - 26)))),
  sleep: (ms) => new Promise((r) => setTimeout(r, Math.min(Number(ms) || 0, 600000))),
  getRandomValues: (arr) => crypto.getRandomValues(arr),
  randomUniform,
  randomUuid: () => crypto.randomUUID(),
  hash: (data, alg) => digest(alg || "sha256", data),
  hmac: (data, key, alg) => digest(alg || "sha256", data, key),
  constant: Object.freeze({
    MODIFIER_SHIFT, MODIFIER_CONTROL, MODIFIER_OPTION, MODIFIER_COMMAND,
    KEY_RETURN: 0x24, KEY_TAB: 0x30, KEY_SPACE: 0x31, KEY_DELETE: 0x33, KEY_ESCAPE: 0x35,
    KEY_LEFTARROW: 0x7b, KEY_RIGHTARROW: 0x7c, KEY_DOWNARROW: 0x7d, KEY_UPARROW: 0x7e,
  }),
};

// ---------------------------------------------------------------- XHR + axios shims

class OmapopXMLHttpRequest {
  constructor() {
    this.readyState = 0; this.status = 0; this.statusText = ""; this.responseText = ""; this.response = null;
    this.responseType = ""; this.timeout = 0; this.onload = null; this.onerror = null; this.onreadystatechange = null;
    this.ontimeout = null; this.onabort = null; this._headers = {}; this._responseHeaders = ""; this._controller = null;
  }
  open(method, url) {
    if (!allowNetwork) throw new Error("XMLHttpRequest needs the network entitlement");
    if (populating) throw new Error("XMLHttpRequest cannot be used while populating actions");
    const u = checkHttpUrl(url);
    this._method = String(method || "GET").toUpperCase(); this._url = u.toString(); this.readyState = 1; this._change();
  }
  setRequestHeader(name, value) { this._headers[String(name)] = String(value); }
  getAllResponseHeaders() { return this._responseHeaders; }
  getResponseHeader(name) { const m = this._responseHeaders.split("\r\n").find((l) => l.toLowerCase().startsWith(String(name).toLowerCase() + ":")); return m ? m.split(":").slice(1).join(":").trim() : null; }
  abort() { if (this._controller) this._controller.abort(); this.readyState = 0; if (this.onabort) this.onabort(); }
  _change() { if (this.onreadystatechange) this.onreadystatechange(); }
  send(body) {
    this._controller = new AbortController();
    const timer = this.timeout > 0 ? setTimeout(() => { this._controller.abort(); if (this.ontimeout) this.ontimeout(); }, this.timeout) : null;
    fetch(this._url, { method: this._method, headers: this._headers, body: body === undefined ? undefined : body, signal: this._controller.signal, redirect: "follow" })
      .then(async (res) => {
        this.status = res.status; this.statusText = res.statusText; this.readyState = 2; this._change();
        const headers = []; res.headers.forEach((v, k) => headers.push(k + ": " + v)); this._responseHeaders = headers.join("\r\n");
        if (this.responseType === "arraybuffer") { this.response = await res.arrayBuffer(); }
        else { const text = await res.text(); this.responseText = text; this.response = this.responseType === "json" ? (() => { try { return JSON.parse(text); } catch (e) { return null; } })() : text; }
        this.readyState = 4; this._change(); if (this.onload) this.onload();
      })
      .catch((err) => { this.readyState = 4; this._change(); if (err && err.name === "AbortError") return; if (this.onerror) this.onerror(err); })
      .finally(() => { if (timer) clearTimeout(timer); });
  }
}

function makeAxios(defaults = {}) {
  async function axiosRequest(config) {
    if (typeof config === "string") config = { url: config };
    config = Object.assign({}, defaults, config || {}, {
      headers: Object.assign({}, defaults.headers || {}, config?.headers || {}),
      params: Object.assign({}, defaults.params || {}, config?.params || {})
    });
    if (!allowNetwork) throw new Error("network access needs the network entitlement");
    const url = new URL(String(config.url), config.baseURL);
    if (config.params) for (const [k, v] of Object.entries(config.params)) url.searchParams.set(k, String(v));
    const method = String(config.method || "GET").toUpperCase();
    const headers = Object.assign({}, config.headers || {});
    let body = config.data;
    if (body !== undefined && typeof body !== "string" && !(body instanceof Uint8Array)) {
      body = JSON.stringify(body);
      if (!Object.keys(headers).some((h) => h.toLowerCase() === "content-type")) headers["Content-Type"] = "application/json";
    }
    if (config.auth) headers["Authorization"] = "Basic " + base64Encode(config.auth.username + ":" + config.auth.password);
    const controller = new AbortController();
    const timer = config.timeout ? setTimeout(() => controller.abort(), config.timeout) : null;
    try {
      const res = await fetch(url.toString(), { method, headers, body, signal: controller.signal });
      const text = await res.text();
      let data = text;
      const type = res.headers.get("content-type") || "";
      if (config.responseType !== "text" && (type.includes("json") || (text && /^[\[{]/.test(text.trim())))) { try { data = JSON.parse(text); } catch (e) { data = text; } }
      const hdrs = {}; res.headers.forEach((v, k) => { hdrs[k] = v; });
      const response = { data, status: res.status, statusText: res.statusText, headers: hdrs, config };
      const validate = config.validateStatus || ((s) => s >= 200 && s < 300);
      if (!validate(res.status)) { const err = new Error("Request failed with status code " + res.status); err.response = response; err.config = config; throw err; }
      return response;
    } finally { if (timer) clearTimeout(timer); }
  }
  const axios = (config) => axiosRequest(config);
  for (const m of ["get", "delete", "head", "options"]) axios[m] = (url, config) => axiosRequest(Object.assign({}, config, { url, method: m }));
  for (const m of ["post", "put", "patch"]) axios[m] = (url, data, config) => axiosRequest(Object.assign({}, config, { url, data, method: m }));
  axios.request = axiosRequest;
  axios.create = (extra = {}) => makeAxios(Object.assign({}, defaults, extra, {
    headers: Object.assign({}, defaults.headers || {}, extra.headers || {}),
    params: Object.assign({}, defaults.params || {}, extra.params || {})
  }));
  axios.defaults = defaults;
  axios.isAxiosError = (e) => !!(e && e.response);
  axios.default = axios;
  return axios;
}

// ---------------------------------------------------------------- require()

const moduleCache = new Map();
const bundled = { axios: makeAxios };

function makeRequire(fromDir) {
  return function require(id) {
    id = String(id);
    if (moduleCache.has(id)) return moduleCache.get(id);
    if (Object.prototype.hasOwnProperty.call(bundled, id)) { const m = bundled[id](); moduleCache.set(id, m); return m; }
    const base = id.startsWith("./") || id.startsWith("../") ? fromDir : packageRoot;
    let path = joinPath(base, id);
    if (!insidePackage(path, packageRoot)) return undefined;
    const candidates = /\.(js|cjs|json|ts)$/.test(path) ? [path] : [path + ".js", path + ".cjs", path + ".json", path + ".ts", path];
    path = candidates.find(fileExists);
    if (!path) return undefined;
    if (moduleCache.has(path)) return moduleCache.get(path);
    const source = readTextFile(path);
    let exported;
    if (path.endsWith(".json")) exported = JSON.parse(source);
    else if (path.endsWith(".ts")) throw new Error("require() of TypeScript files is not supported by this runner; use import in a .ts entry point");
    else {
      const mod = { exports: {} };
      const fn = new Function("module", "exports", "require", "__filename", "__dirname", API_NAME, "util", "pasteboard", "print", "sleep", "defineExtension", "define", "XMLHttpRequest", source + "\n//# sourceURL=" + path);
      fn(mod, mod.exports, makeRequire(dirname(path)), path, dirname(path), api, util, pasteboard, print, util.sleep, defineExtension, define, OmapopXMLHttpRequest);
      exported = mod.exports;
    }
    moduleCache.set(path, exported);
    return exported;
  };
}

let definedExtension = undefined;
function defineExtension(obj) { definedExtension = obj; return obj; }
function define(...args) { const factory = args[args.length - 1]; definedExtension = typeof factory === "function" ? factory() : factory; return definedExtension; }
function print(...args) { emit({ call: "print", args: args.map((a) => (typeof a === "string" ? a : safeStringify(a))) }); }
function safeStringify(v) { try { return JSON.stringify(v); } catch (e) { return String(v); } }

Object.assign(globalThis, {
  [API_NAME]: api, util, pasteboard, print, sleep: util.sleep, defineExtension, define,
  require: makeRequire(packageRoot), XMLHttpRequest: OmapopXMLHttpRequest,
  module: { exports: {} }, exports: {},
});
globalThis.exports = globalThis.module.exports;
if (typeof globalThis.window === "undefined") globalThis.window = globalThis;
if (!allowNetwork) {
  const denied = () => { throw new Error("network access needs the network entitlement"); };
  for (const name of ["fetch", "WebSocket", "EventSource"]) {
    try { Object.defineProperty(globalThis, name, { value: denied, configurable: true, writable: true }); } catch (e) { /* read-only global */ }
  }
}

// ---------------------------------------------------------------- module loading

const MODULE_SYNTAX = /(^|\n)\s*(export\s|import\s)|\bdefineExtension\s*(?:<|\()|\bmodule\.exports\b|\bexports\.[A-Za-z_$]/;

function looksLikeModule(source) {
  const stripped = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|\n)\s*\/\/.*(?=\n|$)/g, "$1");
  return MODULE_SYNTAX.test(stripped);
}

async function loadModule(path) {
  if (!insidePackage(path, packageRoot) || !fileExists(path)) throw new Error("module file not found: " + path);
  const source = readTextFile(path);
  if (!looksLikeModule(source)) {
    // A Config.js/Config.ts snippet can be an action body. Inspecting its
    // metadata must never execute that body or any of its effects.
    return { action: () => runScriptFile(path, source) };
  }
  const esm = /(^|\n)\s*(export\s|import\s)/.test(source.replace(/(^|\n)\s*\/\/.*(?=\n|$)/g, "$1"));
  let exported;
  if (esm || path.endsWith(".ts")) {
    const imported = await import("file://" + path);
    exported = definedExtension !== undefined ? definedExtension : (imported.default !== undefined ? imported.default : imported);
  } else {
    const mod = { exports: {} };
    const fn = new Function("module", "exports", "require", "__filename", "__dirname", source + "\n//# sourceURL=" + path);
    fn(mod, mod.exports, makeRequire(dirname(path)), path, dirname(path));
    exported = definedExtension !== undefined ? definedExtension : mod.exports;
  }
  if (exported && typeof exported === "object" && exported.default && !exported.actions && !exported.action) exported = exported.default;
  return exported;
}

const STATIC_ONLY = new Set(["name", "icon", "identifier", "popclipVersion", "requiredVersion", "macosVersion", "entitlements", "module", "showAs", "offersMultipleInstances", "color", "authServiceLabel", "authKeychain", "shellScriptRationale", "description", "keywords", "language"]);

function camel(key) {
  return String(key).replace(/[ _-]+([a-zA-Z0-9])/g, (m, c) => c.toUpperCase());
}

function extensionDefaults(exported) {
  const defaults = {};
  const skip = new Set(["actions", "action", "submenu", "options", "auth", "test"]);
  for (const [k, v] of Object.entries(exported || {})) if (!skip.has(k) && !STATIC_ONLY.has(k)) defaults[k] = v;
  for (const [k, v] of Object.entries(ext.static || {})) { const ck = camel(k); if (!(ck in defaults) && !STATIC_ONLY.has(ck) && !skip.has(ck)) defaults[ck] = v; }
  return defaults;
}

function resolveActions(exported) {
  let list;
  if (typeof exported === "function") list = [{ code: exported }];
  else if (Array.isArray(exported)) list = exported;
  else if (exported && typeof exported.actions === "function") list = exported.actions(input, options, context);
  else if (exported && Array.isArray(exported.actions)) list = exported.actions;
  else if (exported && exported.actions && typeof exported.actions === "object") list = [exported.actions];
  else if (exported && typeof exported.action === "function") list = [{ code: exported.action }];
  else if (exported && exported.action) list = [exported.action];
  else if (exported && exported.submenu !== undefined) list = [{ submenu: exported.submenu }];
  else list = [];
  if (list && typeof list.then === "function") return list.then((l) => normaliseList(l, exported));
  return normaliseList(list, exported);
}

function normaliseList(list, exported) {
  if (!list) return [];
  if (!Array.isArray(list)) list = [list];
  const defaults = extensionDefaults(exported);
  return list.filter(Boolean).slice(0, 64).map((a) => (typeof a === "function" ? Object.assign({}, defaults, a, { code: a }) : Object.assign({}, defaults, a)));
}

function moduleOptions(exported) {
  const result = [];
  for (const option of (Array.isArray(exported?.options) ? exported.options : []).slice(0, 64)) {
    if (!option || typeof option !== "object" || typeof option.identifier !== "string") continue;
    const type = option.type || "string";
    if (!["string", "secret", "boolean", "multiple", "heading"].includes(type)) continue;
    const text = value => String(typeof value === "object" && value ? value.en ?? Object.values(value)[0] ?? "" : value ?? "")
      .slice(0, 256).replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]/g, "");
    const values = (Array.isArray(option.values) ? option.values : []).slice(0, 200).map(text);
    result.push({ identifier: text(option.identifier).slice(0, 128), type, label: text(option.label || option.identifier),
      description: text(option.description), values,
      valueLabels: (Array.isArray(option.valueLabels || option["value labels"]) ? (option.valueLabels || option["value labels"]) : []).slice(0, 200).map(text),
      defaultValue: type === "boolean" ? (option.defaultValue ?? option["default value"] ?? true) === true : text(option.defaultValue ?? option["default value"] ?? (type === "multiple" ? values[0] : "") ?? ""),
      allowOther: option.allowOther === true, allowNone: option.allowNone === true,
      multiline: option.multiline === true, hidden: option.hidden === true });
  }
  return result;
}

function serialiseAction(a, index, depth) {
  if (!a) return null;
  if (a.separator) return { separator: true, index };
  const out = { index, hasCode: typeof a.code === "function" || typeof a === "function" };
  const copy = (k, cast) => { if (a[k] !== undefined && a[k] !== null) out[k] = cast ? cast(a[k]) : a[k]; };
  copy("title", (v) => typeof v === "object" ? String(v.en || Object.values(v)[0] || "") : String(v).slice(0, 256));
  copy("icon", (v) => (v === null ? "" : String(v).slice(0, 8192)));
  copy("identifier", (v) => String(v).slice(0, 128));
  copy("requirements", (v) => (Array.isArray(v) ? v.map(String).slice(0, 32) : [String(v)]));
  copy("requiredApps", (v) => (Array.isArray(v) ? v.map((s) => String(s).toLowerCase()) : []));
  copy("excludedApps", (v) => (Array.isArray(v) ? v.map((s) => String(s).toLowerCase()) : []));
  copy("before", String); copy("after", String);
  copy("stayVisible", Boolean); copy("captureHtml", Boolean); copy("restorePasteboard", Boolean);
  copy("wantsPrimaryDisplay", Boolean); copy("wantsInitialDisplay", Boolean); copy("showAs", String);
  if (a.regex !== undefined && a.regex !== null) {
    if (a.regex instanceof RegExp) out.regex = { source: a.regex.source, flags: a.regex.flags.replace(/[gy]/g, "") };
    else out.regex = { source: String(a.regex), flags: "" };
  }
  if (a.submenu !== undefined && a.submenu !== null) {
    if (typeof a.submenu === "function") out.submenu = "function";
    else if (depth < 3) out.submenu = (Array.isArray(a.submenu) ? a.submenu : [a.submenu]).map((child, i) => serialiseAction(child, i, depth + 1)).filter(Boolean);
  }
  if (a.url !== undefined) out.url = String(a.url);
  return out;
}

async function locateAction(exported, path) {
  let list = await resolveActions(exported);
  let action = null;
  for (let level = 0; level < path.length; level++) {
    const idx = Number(path[level]);
    action = list[idx];
    if (!action) throw new Error("action index " + path.join("/") + " not found");
    if (level < path.length - 1) {
      let sub = action.submenu;
      if (typeof sub === "function") sub = await sub(input, options, context);
      list = normaliseList(sub, exported);
    }
  }
  return action;
}

// ---------------------------------------------------------------- run

async function runInline(source) {
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  let main;
  try {
    main = new AsyncFunction(source + "\n//# sourceURL=inline.js");
  } catch (e) {
    if (e instanceof SyntaxError && (request.action && request.action.language === "typescript")) throw new Error("inline TypeScript is not supported; save the script as a .ts file in a package");
    throw e;
  }
  return await main();
}

async function main() {
  const action = request.action || {};
  if (mode === "action" && action.javascript) {
    return runInline(String(action.javascript));
  }
  if (mode === "action" && action.javascriptFile && !ext.module) {
    const path = String(action.javascriptFile);
    if (!insidePackage(path, packageRoot) || !fileExists(path)) throw new Error("javascript file not found");
    const source = readTextFile(path);
    if (!looksLikeModule(source)) {
      return runScriptFile(path, source);
    }
    ext.module = path;
  }
  if (!ext.module) throw new Error("nothing to run");
  const exported = await loadModule(String(ext.module));
  const declaredOptions = moduleOptions(exported);
  options = Object.freeze(Object.assign(Object.fromEntries(declaredOptions.map(o => [o.identifier, o.defaultValue])), request.options || {}));
  if (mode === "metadata") return { actions: [], options: declaredOptions };
  if (mode === "populate") {
    const list = await resolveActions(exported);
    return { actions: list.map((a, i) => serialiseAction(a, i, 0)).filter(Boolean), options: declaredOptions };
  }
  if (mode === "submenu") {
    const parent = await locateAction(exported, action.path || [0]);
    let sub = parent.submenu;
    if (typeof sub === "function") sub = await sub(input, options, context);
    const list = normaliseList(sub, exported);
    return { actions: list.map((a, i) => serialiseAction(a, i, 0)).filter(Boolean) };
  }
  const target = await locateAction(exported, action.path || [action.index || 0]);
  const code = typeof target === "function" ? target : target.code;
  if (typeof code !== "function") throw new Error("action has no code");
  return await code(input, options, context);
}

async function runScriptFile(path, source) {
  if (!path.endsWith(".ts")) return runInline(source);
  if (!isDeno) {
    const { stripTypeScriptTypes } = await import("node:module");
    const wrapped = stripTypeScriptTypes("async function omapopInline() {\n" + source + "\n}");
    return runInline(wrapped + "\nreturn await omapopInline();");
  }
  const wrapped = "export default async function() {\n" + source + "\n}";
  const imported = await import("data:application/typescript;base64," + base64Encode(wrapped));
  return await imported.default();
}

try {
  const result = await main();
  if (result && typeof result === "object" && Array.isArray(result.actions)) finish({ actions: result.actions, options: result.options || [] });
  else finish({ result: typeof result === "string" ? result : null });
} catch (err) {
  finish({ error: classifyError(err) });
}
