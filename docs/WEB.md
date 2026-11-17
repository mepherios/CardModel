# From native to the web: one machine, every engine

**Goal (the owner's words, 2026-11-17):** "Make it all so native it can be run in anything from native to html
(functionally)." Read here as: what the cards define must run on any target, from machine code to a web page, with
the same results everywhere, checked and not assumed.

This document covers the first step: **machine modules** (instruction cards, hardware cards, lifted code, whole
machines such as the Game Boy) now run in JavaScript, in a browser page and as WebAssembly, emitted from the same
cards that give the native C library. No machine was ported by hand.

## 1. What runs where

| engine | what runs | made from | integers |
|---|---|---|---|
| `ir` | the reference interpreter | the IR | Python int (exact) |
| `host` | Python, in this process | `language/python` | Python int |
| `native` (`c`) | a shared library | `language/c`, cc | int64, wrapping |
| `javascript` | Node | `language/javascript` | BigInt (exact) |
| `browser` | a Chromium page | `language/javascript` hosted by `platform/browser` | BigInt |
| `wasm` | WebAssembly in Node | `language/c` compiled by `platform/wasm` | int64 (the native words) |
| `wasm@browser` | WebAssembly in a page | `platform/wasm` hosted by `platform/browser` | int64 |

Every engine has the same small API (`machine/native.py`: `call`, `get`, `set`, `array`, `read`, `write`), so the
instruction-card bench, the Game Boy shell (`gb.GameBoy`) and PR #94's foreign-process shell (`process.Process`) run
on any of them by name: `--engine javascript`, `--engines ir,native,wasm@browser`.

## 2. How it is built (all card data)

* **`language/javascript`** gains the machine-state templates the C and Python cards already had: `global`,
  `array`, `array_init`, `load`, `store` (a u8 store is `BigInt.asUintN(8, v)`, like C's `(uint8_t)`), `do`,
  `return_void`, `switch`, and the type `void`. Its new `embed` block has kind **`process`**: the emitted module
  plus a request server (`serve`, about 50 lines of JavaScript) with the module's names filled in from the `entry`
  templates, and a `transport` (Node: one JSON request line on stdin, one answer line on stdout).
* **`platform/browser`** hosts that text in a web page: its embed block replaces the transport
  (`window.cm_serve = cm_serve`) and adds a driver (Node + Playwright + Chromium relays the request lines with
  `page.evaluate`). It also holds `page` and `page_replay`, the templates of the standalone page (§3).
* **`platform/wasm`** compiles the **C card's** module for wasm32 (`clang --target=wasm32 -nostdlib`), inlines it
  as base64 (`preamble`), and serves it with the JavaScript card's server; its `entry` templates map exported C
  globals and arrays to addresses in the module's memory. Its `math.h` is freestanding: only operations that are
  WebAssembly instructions, so a module that needs another libm function fails to build, never links a different
  one.
* **`machine/native.py`**: one generic `ProcessMachine` for all of them. An engine name is `CODE` or `CODE@HOST`
  (`process_parts`); nothing in Python names a language or a platform. Stores and writes are batched and sent with
  the next request that needs an answer, globals are read in one batch and kept until the machine runs again.
* **`engines/probes.py`**: a `command` probe kind (a command that must exit 0), used for "Node can load Playwright"
  and "clang can link wasm32".

`tools/gen_js_machine.py` writes these cards (idempotent; the store versions what changed).

## 3. A page that checks itself

```sh
cardmodel machine page ROM --out game.html [--frames 60] [--page-engine javascript|wasm] [--check]
```

Plays the ROM through the Game Boy shell on a recording JavaScript machine, then answers every recorded request
batch with the **native C library** (`native.serve_request`), and writes one HTML file holding the module, its
server, the batches and the native answers. Opened in any browser (no server, no network, works from `file://`),
the page replays the session and prints `PASS: N of N request batches answer exactly as c did`, or the first
batch that differs. `--check` opens it in Chromium and prints the verdict. A planted wrong answer makes the page
fail (tested).

## 4. Evidence (Linux container, Node 22, Chromium from Playwright)

* `cardmodel isa check lr35902 --engines ir,native,javascript,browser,wasm,wasm@browser`: **512/512** instruction
  cards pass in all six engines (1,056 one-instruction runs, each compared field by field with the reference).
* `cardmodel isa check armv5te --engines ir,native,javascript,browser,wasm,wasm@browser`: **167/167**.
* Game Boy, two synthetic ROMs (serial "Passed", and graphics with a sprite): the same serial text, state hash and
  frame bytes in `native`, `host`, `javascript`, `browser`, `wasm` and `wasm@browser`.
* Pages: 120 frames of the graphics ROM as wasm and 30 frames of the serial ROM as JavaScript, each
  `PASS: all batches answer exactly as c did`.
* A wrong ADD planted in the bench module is caught by the JavaScript engine (CM07).
* **With PR #94 merged locally** (not part of this change): the MIPS sample `algos`, built for MIPS Linux, prints
  the same output and exit code as the same C built for this computer, interpreted and translated, in `native`,
  `javascript`, `browser`, `wasm` and `wasm@browser`.

Speed, the same 14.75M-instruction MIPS run (`work 3`, PR #94), instructions per second:

| engine | interpreted | translated (lifted) |
|---|---|---|
| native (C, -O2) | 217M | 1,360M |
| wasm (Node) | 219M | 463M |
| wasm@browser | 95M | 171M |
| javascript (Node) | 2.3M | 7.8M |
| browser (JavaScript) | 2.7M | 10.2M |

The JavaScript module is exact (BigInt) but about 100 times slower than C; WebAssembly carries the native words and
reaches native speed for the interpreter in Node. Both are correct; choose by need.

## 5. What remains, in order

1. **Native words in JavaScript.** Emit `Number` (or `Int32`) instead of BigInt where the abstract interpreter
   (`machine/absint.py`) proves a value's range, with the conformance runs as the check. That closes most of the
   100x without WebAssembly.
2. **An effect shell in the page.** Today the page replays a recorded session (frames are checked, not drawn). A
   `platform/browser` shell (canvas, keys, audio) driven by the same machine API makes a playable page; the Python
   shell's setup (ROM banking, header) should move into card logic first so the page does not re-implement it.
3. **Programs, not only machines.** Ordinary lifted functions already translate to JavaScript (the conformance
   matrix); give `translate` a `--target browser|wasm` that emits a page or a `.wasm` module with the same witness.
4. **More hosts as cards:** Deno/Bun, a Web Worker, WASI (a `.wasm` with a command-line `_start`), and a
   `platform/ios`/`macos` WebKit view, each one more `platform` card with an embed block.
5. **CI:** the browser and wasm engines skip themselves without Playwright or a wasm-capable clang; the "Every
   language" job should install both.

Honest limits (L1): the browser engine is tested in Chromium only (the page itself uses nothing beyond ES2020 and
WebAssembly 1.0 with bulk memory, so Safari 15+ and Firefox should run it, but that is not yet measured); the
JavaScript engine's speed is BigInt's; a page has no input of its own yet.
