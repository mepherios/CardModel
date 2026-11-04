#!/usr/bin/env bash
# install_toolchains.sh — install the toolchains cardmodel translates to and checks against, where missing.
#
# Used by CI (.github/actions/toolchains) and by the Claude cloud environment's setup script. Safe to re-run:
# each step is skipped when its toolchain is already present. Linux (apt) and macOS (brew).
#
#   lua    5.4 (the lua language card needs >= 5.4)
#   lean   the toolchain pinned in formal/lean-toolchain, through elan (the lean card only looks under
#          ~/.elan/toolchains, so the elan proxy never downloads during a run)
#
# C, C++, Go, Java, JavaScript, Python, Ruby, Rust and Swift come from the host image or CI's setup actions.
# TypeScript runs on Node >= 23.6 (type stripping); this script reports it but does not replace Node.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUDO=""
if [ "$(id -u)" != "0" ] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

have() { command -v "$1" >/dev/null 2>&1; }
log() { printf '[toolchains] %s\n' "$*"; }

# --- Lua 5.4 -----------------------------------------------------------------------------------------------
lua_ok() { have lua && lua -v 2>&1 | grep -Eq 'Lua 5\.([4-9])'; }
if lua_ok; then
  log "lua: $(lua -v 2>&1)"
elif have apt-get; then
  log "lua: installing lua5.4 (apt)"
  { $SUDO apt-get install -y -q lua5.4 >/dev/null 2>&1 || { $SUDO apt-get update -q >/dev/null 2>&1 && $SUDO apt-get install -y -q lua5.4 >/dev/null 2>&1; }; } \
    || log "lua: apt install failed"
  # Debian registers /usr/bin/lua through update-alternatives; make sure it points at 5.4.
  [ -x /usr/bin/lua5.4 ] && ! lua_ok && $SUDO update-alternatives --set lua-interpreter /usr/bin/lua5.4 >/dev/null 2>&1
  lua_ok && log "lua: $(lua -v 2>&1)" || log "lua: still missing"
elif have brew; then
  brew install lua >/dev/null && log "lua: $(lua -v 2>&1)"
else
  log "lua: no package manager found, skipped"
fi

# --- Lean (via elan, pinned toolchain) ---------------------------------------------------------------------
TOOLCHAIN="$(tr -d '[:space:]' < "$ROOT/formal/lean-toolchain" 2>/dev/null || true)"
ELAN="$HOME/.elan/bin/elan"
if [ -z "$TOOLCHAIN" ]; then
  log "lean: formal/lean-toolchain not found, skipped"
else
  if [ ! -x "$ELAN" ]; then
    log "lean: installing elan"
    curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -o /tmp/elan-init.sh \
      && sh /tmp/elan-init.sh -y --default-toolchain none --no-modify-path >/dev/null 2>&1 \
      || log "lean: elan install failed"
  fi
  if [ -x "$ELAN" ]; then
    "$ELAN" toolchain install "$TOOLCHAIN" >/dev/null 2>&1 || true
    "$ELAN" default "$TOOLCHAIN" >/dev/null 2>&1 || true
    ls "$HOME"/.elan/toolchains/*/bin/lean >/dev/null 2>&1 \
      && log "lean: $("$HOME"/.elan/bin/lean --version 2>&1 | head -1)" || log "lean: toolchain $TOOLCHAIN missing"
    if [ -n "${GITHUB_PATH:-}" ]; then echo "$HOME/.elan/bin" >> "$GITHUB_PATH"; fi
  fi
fi

# --- Node >= 23.6 for TypeScript (type stripping) ----------------------------------------------------------
node_ok() { have node && node -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>23||(a==23&&b>=6)?0:1)'; }
if node_ok; then
  log "node: $(node --version)"
elif [ "$(uname -s)" = "Linux" ] && [ "$(uname -m)" = "x86_64" ]; then
  # official Linux build of the latest v24, checked against the release's SHASUMS256.txt; installed under /opt
  BASE="https://nodejs.org/dist/latest-v24.x"
  TMP="$(mktemp -d)"
  if curl -sSfL "$BASE/SHASUMS256.txt" -o "$TMP/SHASUMS256.txt"; then
    FILE="$(grep -oE 'node-v[0-9.]+-linux-x64\.tar\.xz' "$TMP/SHASUMS256.txt" | head -1)"
    if [ -n "$FILE" ] && curl -sSfL "$BASE/$FILE" -o "$TMP/$FILE" \
       && (cd "$TMP" && grep " $FILE\$" SHASUMS256.txt | sha256sum -c - >/dev/null); then
      $SUDO tar -xJf "$TMP/$FILE" -C /opt && NODE_BIN="/opt/${FILE%.tar.xz}/bin"
      log "node: installed $("$NODE_BIN/node" --version) in $NODE_BIN"
      [ -n "${GITHUB_PATH:-}" ] && echo "$NODE_BIN" >> "$GITHUB_PATH"
      grep -qs "$NODE_BIN" "$HOME/.bashrc" || echo "export PATH=\"$NODE_BIN:\$PATH\"" >> "$HOME/.bashrc"
    else
      log "node: download or checksum failed"
    fi
  fi
  rm -rf "$TMP"
else
  log "node: $(node --version 2>/dev/null || echo none) (typescript needs >= v23.6)"
fi

# --- report the rest ---------------------------------------------------------------------------------------
have swiftc && log "swift: $(swiftc --version 2>&1 | head -1)" || log "swift: not installed (swiftc)"
exit 0
