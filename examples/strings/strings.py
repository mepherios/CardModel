"""String functions lifted into the card IR (docs/STRINGS.md) and checked against this file in every target.

`cardmodel translate examples/strings/strings.py` lifts each one and runs it in every available language. A string
is a sequence of Unicode code points, so lengths, indices and comparisons below agree with Python everywhere,
including on non-ASCII text.
"""


def count_char(s: str, c: str) -> int:
    n = 0
    for x in s:
        if x == c:
            n += 1
    return n


def reverse(s: str) -> str:
    out = ""
    for i in range(len(s)):
        out = s[i] + out
    return out


def is_palindrome(s: str) -> bool:
    i = 0
    j = len(s) - 1
    while i < j:
        if s[i] != s[j]:
            return False
        i += 1
        j -= 1
    return True


def caesar(s: str, k: int) -> str:
    """Shift the ASCII lower-case letters by k; every other code point stays."""
    out = ""
    for c in s:
        o = ord(c)
        if 97 <= o <= 122:
            out += chr(97 + (o - 97 + k) % 26)
        else:
            out += c
    return out


def upper_ascii(s: str) -> str:
    out = ""
    for c in s:
        if "a" <= c <= "z":
            out += chr(ord(c) - 32)
        else:
            out += c
    return out


def common_prefix(a: str, b: str) -> int:
    n = 0
    while n < len(a) and n < len(b) and a[n] == b[n]:
        n += 1
    return n


def order(a: str, b: str) -> int:
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def count_occurrences(s: str, sub: str) -> int:
    """Non-overlapping occurrences of a non-empty sub (0 for an empty one)."""
    if len(sub) == 0:
        return 0
    n = 0
    i = s.find(sub)
    while i >= 0:
        n += 1
        i = s.find(sub, i + len(sub))
    return n


def utf8_size(s: str) -> int:
    """The number of bytes s takes in UTF-8, from its code points."""
    n = 0
    for c in s:
        o = ord(c)
        if o < 0x80:
            n += 1
        elif o < 0x800:
            n += 2
        elif o < 0x10000:
            n += 3
        else:
            n += 4
    return n


def scan_int(s: str, pos: int) -> int:
    """What scanf's %d reads at pos: skip spaces, an optional sign, then decimal digits (0 when there are none)."""
    i = pos
    while 0 <= i < len(s) and s[i] in " \t\n":
        i += 1
    neg = False
    if 0 <= i < len(s) and (s[i] == "-" or s[i] == "+"):
        neg = s[i] == "-"
        i += 1
    v = 0
    while 0 <= i < len(s) and "0" <= s[i] <= "9":
        v = v * 10 + ord(s[i]) - 48
        i += 1
    return -v if neg else v


def sum_fields(s: str) -> int:
    """The sum of comma-separated decimal fields ("12, -3,4"): find, slice and int."""
    total = 0
    start = 0
    while start <= len(s):
        end = s.find(",", start)
        if end < 0:
            end = len(s)
        total += int(s[start:end])
        start = end + 1
    return total


def pad_int(n: int, width: int) -> str:
    t = str(n)
    while len(t) < width:
        t = "0" + t
    return t


def label(v: int) -> str:
    """Strings and ints mixed: a sign word and the digits."""
    if v < 0:
        return "minus " + str(-v)
    if v == 0:
        return "zero"
    return "plus " + str(v) + " été \U0001f600"


def contains_both(s: str, a: str, b: str) -> bool:
    return a in s and b not in s[:1] and s.startswith(a[:1]) and s.endswith(b[len(b):])


def strip_leading(s: str, c: str) -> str:
    """Re-binds its string parameter (Rust copies a &str parameter into a String first)."""
    while len(c) == 1 and s.startswith(c):
        s = s[1:]
    return s
