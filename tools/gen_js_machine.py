"""gen_js_machine — write the JavaScript card's machine-state templates and the browser platform card.

The text below is card data: the JavaScript language card gains what a machine module needs (globals, arrays,
loads and stores, ``switch``, void functions) and an ``embed`` block of kind ``process`` (the emitted module plus a
small request server, run by Node); ``platform/browser`` hosts the same module in a web page (Chromium, driven by
Playwright), so the browser is one more engine of ``machine/native.py``. Re-running is idempotent: the store
versions a card only when its content changes.

    python -B tools/gen_js_machine.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.kernel.store import open_store  # noqa: E402

MACHINE_TEMPLATES = {
    "global": "let {name} = {value};",
    "array": {"int": "const {name} = new Array({size}).fill(0n);", "u8": "const {name} = new Uint8Array({size});"},
    "array_init": {"int": "const {name} = [{values}].map(BigInt);", "u8": "const {name} = new Uint8Array([{values}]);"},
    "load": {"int": "{arr}[Number({idx})]", "u8": "BigInt({arr}[Number({idx})])"},
    "store": {"int": "{arr}[Number({idx})] = {value};",
              "u8": "{arr}[Number({idx})] = Number(BigInt.asUintN(8, {value}));"},
    "do": "{value};",
    "return_void": "return;",
    "switch": {"head": "switch ({value}) {{", "case": "case {v}:", "body_open": "{{", "body_close": "}} break;",
               "default": "default:", "tail": "}}"},
}

# The request server, appended to an emitted module. A request line is a JSON array of requests; the answer line is
# a JSON array of {"ok": value} (or one {"error": text}, after which the rest of the batch is skipped). Integers
# travel as decimal strings (they are BigInt here, exact at any size), bytes of a u8 array as hex.
SERVE = r"""
const cm_fns = {
@functions@
};
const cm_vars = {
@globals@
};
const cm_arrs = {
@arrays@
};
function cm_val(v) { return typeof v === 'string' ? BigInt(v) : v; }
function cm_out(v) { return typeof v === 'bigint' ? v.toString() : (v === undefined ? null : v); }
const cm_hexd = Array.from({ length: 256 }, (_, i) => (i < 16 ? '0' : '') + i.toString(16));
function cm_serve_one(r) {
    if (r.op === 'call') return cm_out(cm_fns[r.name](...r.args.map(cm_val)));
    if (r.op === 'get') return cm_out(cm_vars[r.name][0]());
    if (r.op === 'set') { cm_vars[r.name][1](cm_val(r.value)); return null; }
    const a = cm_arrs[r.name];
    if (a === undefined) throw new RangeError('no array ' + r.name);
    const s = r.start || 0;
    if (r.op === 'read') {
        const e = r.n == null ? a.length : Math.min(a.length, s + r.n);
        if (!(a instanceof Uint8Array)) return Array.from(a.slice(s, e), cm_out);
        const parts = new Array(Math.max(0, e - s));
        for (let i = s; i < e; i++) parts[i - s] = cm_hexd[a[i]];
        return parts.join('');
    }
    if (r.op === 'write') {
        if (a instanceof Uint8Array) {
            const n = r.data.length >> 1;
            if (s < 0 || s + n > a.length) throw new RangeError('write past the end of ' + r.name);
            for (let i = 0; i < n; i++) a[s + i] = parseInt(r.data.substr(2 * i, 2), 16);
        } else {
            if (s < 0 || s + r.data.length > a.length) throw new RangeError('write past the end of ' + r.name);
            r.data.forEach((v, i) => { a[s + i] = BigInt(v); });
        }
        return null;
    }
    throw new RangeError('unknown request ' + r.op);
}
function cm_serve(line) {
    const out = [];
    for (const r of JSON.parse(line)) {
        try { out.push({ ok: cm_serve_one(r) }); }
        catch (e) { out.push({ error: String((e && e.stack) || e) }); break; }
    }
    return JSON.stringify(out);
}
"""

NODE_TRANSPORT = r"""
const cm_rl = (await import('node:readline')).createInterface({ input: process.stdin });
for await (const line of cm_rl) process.stdout.write(cm_serve(line) + '\n');
"""

JS_EMBED = {
    "kind": "process",
    "file": "machine.mjs",
    "run": ["{exe}", "{src}"],
    "serve": SERVE,
    "entry": {"function": "    \"@key@\": @name@,",
              "global": "    \"@key@\": [() => @name@, (v) => { @name@ = v; }],",
              "array": "    \"@key@\": @name@,"},
    "transport": NODE_TRANSPORT,
    "statement": "the emitted module and a request server (serve) run in a Node process: one JSON request line in, "
                 "one answer line out; integers are BigInt (exact, like the reference interpreter) and travel as "
                 "decimal strings, u8 arrays are Uint8Array and travel as hex",
}

BROWSER_DRIVER = r"""// Hosts a machine module in a Chromium page and relays request lines to it (platform/browser card).
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const browser = await chromium.launch();
const page = await browser.newPage();
page.on('pageerror', (e) => { process.stderr.write('page error: ' + e + '\n'); process.exit(3); });
await page.setContent('<!doctype html><meta charset="utf-8"><title>cardmodel machine</title><body></body>');
await page.addScriptTag({ type: 'module', content: readFileSync(process.argv[2], 'utf8') });
await page.waitForFunction(() => typeof window.cm_serve === 'function');
const rl = createInterface({ input: process.stdin });
for await (const line of rl) process.stdout.write(await page.evaluate((l) => window.cm_serve(l), line) + '\n');
await browser.close();
"""

# A standalone page: the module and its server run when the page opens; ``@body@`` is the page's own program.
PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@title@</title>
<style>
:root { color-scheme: light dark; --bg: #fff; --fg: #111; }
@media (prefers-color-scheme: dark) { :root { --bg: #111; --fg: #eee; } }
body { background: var(--bg); color: var(--fg); font: 14px/1.45 ui-monospace, Menlo, Consolas, monospace;
       margin: 0; padding: 16px; }
pre { white-space: pre-wrap; word-break: break-word; }
</style>
</head>
<body>
<h1>@title@</h1>
<pre id="out">running…</pre>
<script type="module">
@module@
window.cm_serve = cm_serve;
@body@
</script>
</body>
</html>
"""

# The page's program for a recorded session: replay every request batch and compare each answer with the
# reference engine's (recorded natively). The verdict is shown and kept in <body data-result=...>.
PAGE_REPLAY = r"""
const cm_batches = @batches@;
const cm_expected = @expected@;
const cm_view = document.getElementById('out');
const cm_t0 = performance.now();
let cm_same = 0, cm_first = -1, cm_error = '';
for (let i = 0; i < cm_batches.length; i++) {
    const got = JSON.parse(cm_serve(JSON.stringify(cm_batches[i])));
    const bad = got.find((r) => 'error' in r);
    if (bad) { cm_error = bad.error; cm_first = i; break; }
    if (JSON.stringify(got.map((r) => r.ok)) === JSON.stringify(cm_expected[i])) cm_same++;
    else if (cm_first < 0) cm_first = i;
}
const cm_ms = Math.round(performance.now() - cm_t0);
const cm_pass = cm_same === cm_batches.length && !cm_error;
document.body.dataset.result = cm_pass ? 'pass' : 'fail';
cm_view.textContent = (cm_pass ? 'PASS: ' : 'FAIL: ') + cm_same + ' of ' + cm_batches.length +
    ' request batches answer exactly as @reference@ did (' + cm_ms + ' ms in this browser).\n' +
    (cm_first >= 0 ? 'first difference at batch ' + cm_first + '\n' : '') + (cm_error ? cm_error + '\n' : '') +
    '\nmachine: @machine@\nsession: @session@\nengine: this page (@engine@, emitted from the cards)';
"""

# Opens a page file in Chromium and prints its verdict line (data-result) and its text.
PAGE_CHECK = r"""import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const browser = await chromium.launch();
const page = await browser.newPage();
page.on('pageerror', (e) => { process.stdout.write('error\n' + e + '\n'); process.exit(3); });
await page.goto(pathToFileURL(process.argv[2]).href);
await page.waitForFunction(() => document.body.dataset.result, null, { timeout: 600000 });
process.stdout.write(await page.evaluate(() => document.body.dataset.result + '\n' + document.getElementById('out').textContent) + '\n');
await browser.close();
"""

# WebAssembly: the C card's module compiled for wasm32 and served by the JavaScript request server. The C module's
# exported functions are wasm functions (int64 is a BigInt in JavaScript), its exported globals and arrays are
# addresses in the module's memory. ``math.h`` is freestanding: only operations WebAssembly has as instructions, so
# a module that needs another libm function fails to build instead of linking something else.
WASM_MATH_H = """/* freestanding math for wasm32 (platform/wasm card): WebAssembly instructions only */
#define sqrt(x) __builtin_sqrt(x)
#define fabs(x) __builtin_fabs(x)
#define floor(x) __builtin_floor(x)
#define ceil(x) __builtin_ceil(x)
#define trunc(x) __builtin_trunc(x)
#define nearbyint(x) __builtin_nearbyint(x)
#define copysign(x, y) __builtin_copysign(x, y)
#define fmin(x, y) __builtin_fmin(x, y)
#define fmax(x, y) __builtin_fmax(x, y)
#define INFINITY __builtin_inf()
#define NAN __builtin_nan("")
#define isnan(x) __builtin_isnan(x)
#define isinf(x) __builtin_isinf(x)
#define signbit(x) __builtin_signbit(x)
"""

WASM_PREAMBLE = r"""
const cm_wasm = await WebAssembly.instantiate(Uint8Array.from(atob('@wasm_b64@'), (c) => c.charCodeAt(0)), {});
const cm_x = cm_wasm.instance.exports;
const cm_u8 = new Uint8Array(cm_x.memory.buffer);
const cm_dv = new DataView(cm_x.memory.buffer);
"""

WASM = {
    "name": "wasm",
    "category": "platform",
    "statement": "WebAssembly. The C language card's machine module compiled for wasm32 (clang, no libc) and served "
                 "by the JavaScript request server, so it runs wherever JavaScript runs: Node, and any browser "
                 "(engine wasm@browser). Integers are the C card's int64, the same words as the native library.",
    "language": "c",
    "embed": {
        "kind": "process",
        "language": "c",
        "server": "javascript",
        "exported_only": True,
        "compiler": {"probe": {"kind": "command",
                               "run": ["clang", "--target=wasm32", "-nostdlib", "-Wl,--no-entry", "-o", "/dev/null",
                                       "-x", "c", "/dev/null"],
                               "reason": "clang cannot build wasm32 here (it needs the WebAssembly target and wasm-ld)"},
                     "name": "clang"},
        "compile": ["{exe}", "--target=wasm32", "-O2", "-mbulk-memory", "-std=c11", "-nostdlib", "-fwrapv",
                    "-fvisibility=default", "-w", "-I{include}", "-Wl,--no-entry", "-Wl,--export-dynamic",
                    "-o", "{out}", "{src}"],
        "headers": {"math.h": WASM_MATH_H},
        "source_file": "machine.c",
        "artifact_file": "machine.wasm",
        "preamble": WASM_PREAMBLE,
        "entry": {
            "function": {"bool": "    \"@key@\": (...a) => cm_x.@name@(...a) !== 0,",
                         "default": "    \"@key@\": cm_x.@name@,"},
            "global": {"bool": "    \"@key@\": [() => cm_u8[cm_x.@name@.value] !== 0, "
                               "(v) => { cm_u8[cm_x.@name@.value] = v ? 1 : 0; }],",
                       "float": "    \"@key@\": [() => cm_dv.getFloat64(cm_x.@name@.value, true), "
                                "(v) => cm_dv.setFloat64(cm_x.@name@.value, v, true)],",
                       "default": "    \"@key@\": [() => cm_dv.getBigInt64(cm_x.@name@.value, true), "
                                  "(v) => cm_dv.setBigInt64(cm_x.@name@.value, v, true)],"},
            "array": {"u8": "    \"@key@\": cm_x.@name@ && new Uint8Array(cm_x.memory.buffer, cm_x.@name@.value, @size@),",
                      "int": "    \"@key@\": cm_x.@name@ && new BigInt64Array(cm_x.memory.buffer, cm_x.@name@.value, @size@),"},
        },
        "statement": "compile the C module to wasm32, inline it (base64) before the JavaScript request server; the "
                     "server's transport (Node, or a hosting platform's such as the browser's) runs it",
    },
    "honest_limits": "No libc: a machine module that calls a libm function other than the WebAssembly instructions "
                     "does not build. Memory is the module's static data; machine modules allocate nothing.",
}

BROWSER = {
    "name": "browser",
    "category": "platform",
    "statement": "A web page. A machine module emitted by the JavaScript language card runs in the page itself; "
                 "the same text that runs in Node runs here, so a browser is one more engine with the same "
                 "results. Tests drive the page through Chromium (Playwright); `page` is a standalone HTML file "
                 "that needs nothing but a browser.",
    "language": "javascript",
    "embed": {
        "kind": "process",
        "language": "javascript",
        "transport": "\nwindow.cm_serve = cm_serve;\n",
        "driver": {"file": "driver.mjs", "text": BROWSER_DRIVER},
        "run": ["{exe}", "{driver}", "{src}"],
        "probe": {"kind": "all", "of": [
            {"kind": "executable", "name": "node", "version_args": ["--version"]},
            {"kind": "command", "run": ["node", "-e", "require('playwright')"],
             "reason": "the Node module playwright (and its Chromium) is not installed"}]},
        "statement": "the module runs in a Chromium page; a Node driver relays the request lines with page.evaluate",
    },
    "page": PAGE,
    "page_replay": PAGE_REPLAY,
    "page_check": {"file": "check.mjs", "text": PAGE_CHECK, "run": ["{exe}", "{driver}", "{page}"]},
    "honest_limits": "Integers are BigInt, exact but slower than machine words; a page has no files, so the effect "
                     "shell (ROM loading, display, sound) is the page's own program.",
}


def main() -> int:
    store = open_store(project=False)
    lang = dict(store.get("language/javascript"))
    cg = dict(lang["codegen"])
    cg.update(MACHINE_TEMPLATES)
    cg["types"] = {**cg["types"], "void": "void"}
    lang["codegen"] = cg
    lang["embed"] = JS_EMBED
    _, changed = store.save(lang, category="language")
    print("language/javascript", "changed" if changed else "unchanged")
    for card in (BROWSER, WASM):
        _, changed = store.save(card, category="platform")
        print(f"platform/{card['name']}", "changed" if changed else "unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
