# Strings

The IR has a `str` type. A string is an immutable value: a sequence of Unicode code points (scalar values, that
is code points other than the surrogates U+D800 to U+DFFF). Lengths, indices, slices and comparisons count code
points. They never count bytes, UTF-16 units or graphemes. This is Python's `str`, so a lifted function means the
same thing in every target, on any text.

```
cardmodel translate examples/strings/strings.py      # 15 string functions, every available language
```

[examples/strings/strings.py](../examples/strings/strings.py) reverses strings, checks palindromes, runs a Caesar
shift, upper-cases ASCII, finds common prefixes, orders strings, counts occurrences, measures UTF-8 size, scans an
int the way scanf's `%d` does (`scan_int`), sums comma-separated fields (`find`, slicing and `int`), pads numbers,
mixes text with ints and strips a leading character (re-binding its parameter). Every function agrees with the Python original in C, C++, Go, Java, JavaScript, Lua,
Python, Ruby, Rust and TypeScript.

## Why code points

Code points are the only unit every target can compute exactly. Bytes would differ by encoding, UTF-16 units would
split an emoji in two, and graphemes need Unicode's segmentation tables, which change with each Unicode version.
Python already counts code points, so lifted code needs no translation of meaning. The cost lands in the targets
whose native string is something else: those index through a code-point array (see the table below), which is
O(n) per index. A target that needs byte-exact C semantics on non-ASCII text (C's `char *`, `sscanf`) needs a
separate `bytes` sort. That sort is not built yet. On ASCII text the two agree.

## Ops

Each op is a card in `cards/op/` with its reference semantics (`ir.eval`), its domain for the conformance matrix
and one template per language.

| IR | Python | meaning |
|---|---|---|
| `["str", "text"]` | `"text"` | a literal |
| `["STR_LEN", s]` | `len(s)` | the number of code points |
| `["STR_AT", s, i]` | `ord(s[i])` | the code point at i, as an int. 0 ≤ i < len, or an error (no negative indexing, as with lists) |
| `["STR_FROM_CODE", c]` | `chr(c)` | a one-character string. A surrogate or a value outside 0..U+10FFFF is an error (Python allows a lone surrogate; no target can hold it as text) |
| `["STR_ORD", s]` | `ord(s)` | the code point of a one-character string; any other length is an error |
| `["STR_CONCAT", a, b]` | `a + b` | concatenation |
| `["STR_EQ", a, b]` | `a == b` | the same code points in order. No normalization: `"é"` is not `"é"` |
| `["STR_CMP", a, b]` | — | -1, 0 or 1, lexicographic by code point (Python's order) |
| `["STR_SLICE", s, a, b]` | `s[a:b]` | Python's slice: a negative bound counts from the end, bounds clamp to 0..len, a ≥ b gives `""`. Never an error |
| `["STR_FIND", s, sub, start]` | `s.find(sub, start)` | the lowest index ≥ start where sub occurs, or -1. A negative start counts from the end; a start past the end finds nothing, not even `""` |
| `["STR_FROM_INT", n]` | `str(n)` | decimal text |
| `["STR_TO_INT", s]` | `int(s)` | optional ASCII whitespace (space, tab, LF, VT, FF, CR), an optional sign, one or more ASCII digits, optional ASCII whitespace. Anything else is an error |

`STR_TO_INT` is stricter than Python's `int()`, which also accepts underscores between digits (`"1_000"`) and
non-ASCII digits and spaces. The frontend lifts `int(s)` to this op, so such inputs are outside the lifted
function's domain. On such an input the IR fails where Python returns a number. The translate witness then stops
with the IR's error, because it never skips a failure the Python source does not share. The generators produce
no underscores and no non-ASCII digits.

These ops are the primitives scanning needs (AnyPS5's `vsscanf` and `vfscanf` wait on them). `STR_AT` reads a code
point at a position and `STR_FIND` locates a delimiter. `STR_SLICE` cuts a field and `STR_TO_INT` converts it.
`scan_int` and `sum_fields` in the example are `%d` and a field splitter written with them.

## What the Python frontend lifts

| Python | IR |
|---|---|
| `s: str` parameters, locals and results; string literals | type `str`, `["str", ...]` |
| `len(s)` | `STR_LEN` |
| `s[i]` | `STR_FROM_CODE(STR_AT(s, i))`. `ord(s[i])` is `STR_AT(s, i)` |
| `s[a:b]`, `s[:b]`, `s[a:]` | `STR_SLICE` (a missing bound is 0 or `STR_LEN(s)`) |
| `a + b`, `s += t` | `STR_CONCAT` |
| `a == b`, `a != b` | `STR_EQ`, `NOT(STR_EQ)` |
| `a < b`, `<=`, `>`, `>=` (chains too) | `CMP_xx(STR_CMP(a, b), 0)` |
| `sub in s`, `sub not in s` | `STR_FIND(s, sub, 0) >= 0` |
| `s.find(sub)`, `s.find(sub, start)` | `STR_FIND` |
| `s.startswith(p)`, `s.endswith(p)` | `STR_EQ` of a `STR_SLICE` with p |
| `str(n)` for an int, `int(s)`, `ord(c)`, `chr(n)` | `STR_FROM_INT`, `STR_TO_INT`, `STR_ORD`, `STR_FROM_CODE` |
| `for c in s` | a loop over the indices of a copy of s taken before the loop; c is `STR_FROM_CODE(STR_AT(copy, i))` |

Everything else involving a string is reported as unsupported, with its line, and never pasted through:
f-strings, `%` formatting, repetition (`s * n`), other methods (`upper`, `split`, `join`, ...), `str()` of a float
or a bool (their text differs between targets), `int(s, base)`, negative indices, slices with a step, the
truthiness of a string, comparing a string with a number, string defaults, `bytes`, and literals with a lone
surrogate.

## How each target realizes it

| target | type | length and indexing | order and equality |
|---|---|---|---|
| Python | `str` | native (helpers only add the errors Python lacks: `s[-1]`, `chr(0xD800)`, the strict `int`) | native |
| C, C++ | `cm_s`, a struct of `int64_t n` and `uint32_t *d` (one code point per element) | O(1) on the array | element by element |
| Go | `string` (UTF-8) | through `[]rune(s)` | native `<` (UTF-8 byte order is code point order) |
| Java | `String` (UTF-16) | `codePointCount`, `offsetByCodePoints`, `codePoints()` | `Arrays.compare` of the code point arrays. `compareTo` would compare UTF-16 units |
| JavaScript, TypeScript | `string` (UTF-16) | `Array.from(s)` iterates code points | the code point arrays. `<` compares UTF-16 units |
| Ruby | `String` (UTF-8) | native: Ruby counts characters | `codepoints <=>` |
| Rust | `String`; parameters are `&str` | `chars()` | native `cmp` (UTF-8 byte order) |
| Lua 5.4 | `string` (UTF-8 bytes) | the `utf8` library (`utf8.len`, `utf8.offset`, `utf8.codes`) | the code point arrays. `<` uses the C locale's collation |
| Swift | `String` | `unicodeScalars` | the scalar arrays. Swift's `==` and `count` work on graphemes (`"\u{e9}" == "e\u{301}"`) |
| Lean | no template yet: every str op is an `EmitGap` | — | — |

A literal is written with the language card's `str_lit`. Printable ASCII other than quote and backslash stays as
it is, and every other code point is escaped: `\U0001f600` (Python, Go), `\u{1f600}` (JavaScript, Rust, Ruby,
Lua, Swift), or a surrogate pair `😀` in Java. Java's ASCII escapes are octal, because Java replaces
`"` with a quote before it reads the literal. Ruby also escapes `#`, so `#{` cannot interpolate. C and C++
spell a literal as its code point array (`codes`). Rust reads a `String` variable as `s.to_string()` (`var_read`),
so a read never moves it, and passes strings to calls as `&{e}` (`arg_types`).

## Verification

The conformance matrix has one cell per str op and language. Its default alphabet (`values.ALPHABET`) holds ASCII
letters and digits, the controls NUL, tab, LF and DEL, quote, backslash and `# $ { } %`, `é ß`, the combining
acute U+0301, `中`, U+FF5E, U+1F600 and U+10348, so escaping, 2-, 3- and 4-byte UTF-8 and surrogate pairs all
appear. The empty string is always an edge input. The ops' own domains add pointed edges:

* `STR_CMP` and `STR_EQ` pair U+FF5E with U+1F600 (which UTF-16 orders the other way) and `é` with `e` + U+0301
  (which Swift calls equal);
* `STR_LEN` tries a flag (two regional indicators), `\r\n` and `e` + U+0301 (one grapheme each);
* `STR_FROM_CODE` tries 0x7F, 0x80, 0x7FF, 0x800, 0xD7FF, 0xE000, 0xFFFF, 0x10000 and 0x10FFFF;
* `STR_TO_INT` tries `" 12 "`, `"007"`, `"-0"` and the int64 bounds.

A string result is printed as `s:` followed by its code points in decimal (`s:104 105`, or `s:` alone for the
empty string). No target's console encoding or escaping is involved. `tests/test_strings.py` checks the reference
semantics, the lift, the unsupported reports and the literal escapes. It also checks that naive templates fail
the matrix: JavaScript's `.length` on an emoji, and Java's `compareTo` on U+FF5E against U+1F600.

When a function takes a string parameter, `translate` tries the full alphabet first, then a small one where
equal pieces are likely, then decimal digits (for functions that parse their argument).

## Not yet

* Lean has no string templates. Its `String` counts code points too, so the gap is templates, not semantics.
  Swift's templates are written but untested: no Swift toolchain was on the machine that wrote them.
* No string notation in `cardmodel math`: a function with strings is an `EmitGap` there.
* No `bytes` sort, formatting, `split`/`join`, case mapping beyond ASCII, or lists of strings.
* The stdin harnesses (`harness.read`, branch `claude/stdin-harness`) need a `read.str` template per language. One
  that reads the same line `s:` prints (the code points in decimal) needs no escaping in any target.
