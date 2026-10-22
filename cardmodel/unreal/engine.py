"""engine — an Unreal Engine install, found and compiled against without writing to it.

Where the engine is (first that answers): ``--engine PATH``, ``CARDMODEL_UNREAL``, or the Epic launcher's own record
of what it installed (``LauncherInstalled.dat`` under the user's Application Support; the newest UE_* entry). The
version comes from ``Engine/Build/Build.version``.

Two builds of the same sources:
  truth    the engine's scalar path: vector intrinsics off, so every function reads as plain arithmetic (the engine's
           own FPU fallback, ``UnrealMathFPU.h``, stands in for its SIMD registers). The two platform headers that
           force NEON on Apple silicon are copied into the cache with that one line changed; everything else is
           read where it is installed.
  shipped  as the engine runs on this machine (NEON), plus its Core library for what is compiled out of line.
Both define what UnrealBuildTool would for a Development build of a program, with checks and ensures compiled
out (they are diagnostics, not mathematics).

Honest limits (L1): the defines are this module's reading of what UBT passes, checked by compiling the engine's own
headers and .cpp files (``probe``), not taken from UBT; only macOS installs are supported (the defines and the Core
library name are the Mac ones); the truth build's scalar path is the engine's reference for its SIMD code, and the
witness says how far the shipped build is from it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from ..kernel import resources

LAUNCHER = ("Library", "Application Support", "Epic", "UnrealEngineLauncher", "LauncherInstalled.dat")
DEFINES = ["UBT_COMPILED_PLATFORM=Mac", "PLATFORM_MAC=1", "PLATFORM_APPLE=1", "UE_BUILD_DEVELOPMENT=1",
           "WITH_EDITOR=0", "WITH_ENGINE=0", "WITH_UNREAL_DEVELOPER_TOOLS=0", "WITH_PLUGIN_SUPPORT=0",
           "WITH_SERVER_CODE=1", "UE_MERGED_MODULES=0", "IS_MONOLITHIC=1", "IS_PROGRAM=1", "CORE_API=",
           "TRACELOG_API=", "AUTORTFM_API=", "DO_CHECK=0", "DO_ENSURE=0", "DO_GUARD_SLOW=0"]
WARNINGS = ["-Wno-macro-redefined", "-Wno-ignored-attributes", "-Wno-deprecated-declarations", "-Wno-#warnings"]
# the two lines that turn the engine's vector intrinsics on for Apple platforms, and what the truth build reads
SHADOW = {("Apple", "ApplePlatform.h"): (r"^#define PLATFORM_ENABLE_VECTORINTRINSICS\s+1\s*$",
                                         "#define PLATFORM_ENABLE_VECTORINTRINSICS 0"),
          ("Mac", "MacPlatform.h"): (r"^#define PLATFORM_ENABLE_VECTORINTRINSICS_NEON\s+PLATFORM_MAC_ARM64\s*$",
                                     "#define PLATFORM_ENABLE_VECTORINTRINSICS_NEON 0")}
PLATFORM_MATH = ("GenericPlatform/GenericPlatformMath.h", "Clang/ClangPlatformMath.h", "Apple/ApplePlatformMath.h",
                 "Mac/MacPlatformMath.h")


SUPPORT = {"Engine/Source/Runtime/Core/Public/Containers/EnumAsByte.h",
           "Engine/Source/Runtime/Core/Public/Templates/UnrealTemplate.h",
           "Engine/Source/Runtime/Core/Public/Templates/IntegralConstant.h",
           "Engine/Source/Runtime/Core/Public/Misc/IntCast.h"}


class NotFound(Exception):
    """No engine install, or one this module cannot compile against (the reason says which)."""


@dataclass
class Engine:
    root: Path
    version: dict

    @property
    def tag(self) -> str:
        v = self.version
        return f"{v.get('MajorVersion')}.{v.get('MinorVersion')}.{v.get('PatchVersion')}"

    @property
    def changelist(self) -> int | None:
        return self.version.get("Changelist")

    @property
    def runtime(self) -> Path:
        return self.root / "Engine" / "Source" / "Runtime"

    @property
    def core_public(self) -> Path:
        return self.runtime / "Core" / "Public"

    def rel(self, path: str | Path) -> str:
        """A path inside the install, relative to its root (provenance never names the machine's folders)."""
        p = str(path)
        r = str(self.root).rstrip("/") + "/"
        return p[len(r):] if p.startswith(r) else p

    def core_library(self) -> Path | None:
        p = self.root / "Engine" / "Binaries" / "Mac" / "libUnrealEditor-Core.dylib"
        return p if p.is_file() else None

    def headers(self) -> list[Path]:
        """The math headers: Core/Public/Math (with its .inl files) and the platform math the FMath API inherits."""
        math = sorted(p for p in (self.core_public / "Math").iterdir() if p.suffix in (".h", ".inl"))
        return math + [self.core_public / p for p in PLATFORM_MATH if (self.core_public / p).is_file()]

    def sources(self) -> list[Path]:
        """The engine's own math translation units (compiled out of line into Core)."""
        d = self.runtime / "Core" / "Private" / "Math"
        return sorted(d.glob("*.cpp")) if d.is_dir() else []

    def is_math_file(self, path: str) -> bool:
        if not path:
            return False
        r = self.rel(path)
        return (r.startswith("Engine/Source/Runtime/Core/Public/Math/")
                or r.startswith("Engine/Source/Runtime/Core/Private/Math/")
                or r == "Engine/Source/Runtime/Core/Private/GenericPlatform/GenericPlatformMath.cpp"
                or any(r == f"Engine/Source/Runtime/Core/Public/{p}" for p in PLATFORM_MATH))

    @staticmethod
    def is_support_file(rel: str) -> bool:
        """Headers outside the math directory whose types the math uses (kept for their layouts)."""
        return rel in SUPPORT


def _version(root: Path) -> dict:
    f = root / "Engine" / "Build" / "Build.version"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NotFound(f"{f}: not an engine install ({type(exc).__name__})") from exc


def installs() -> list[tuple[str, Path]]:
    """What the Epic launcher recorded: (app name, install location) for every UE_* install."""
    f = Path.home().joinpath(*LAUNCHER)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [(e.get("AppName", ""), Path(e["InstallLocation"])) for e in data.get("InstallationList") or []
            if str(e.get("AppName", "")).startswith("UE_") and e.get("InstallLocation")]


def locate(explicit: str | Path | None = None) -> Engine:
    """The engine to read: an explicit path, CARDMODEL_UNREAL, or the newest install the launcher recorded."""
    cand = explicit or os.environ.get("CARDMODEL_UNREAL")
    if cand:
        root = Path(cand).expanduser()
    else:
        found = [(name, p) for name, p in installs() if (p / "Engine" / "Build" / "Build.version").is_file()]
        if not found:
            raise NotFound("no Unreal Engine install: pass --engine PATH or set CARDMODEL_UNREAL (the Epic "
                           "launcher's record lists none)")
        root = max(found, key=lambda np: tuple(int(x) for x in re.findall(r"\d+", np[0])))[1]
    if not (root / "Engine" / "Source" / "Runtime" / "Core" / "Public" / "Math").is_dir():
        raise NotFound(f"{root}: no Engine/Source/Runtime/Core/Public/Math (an install without source?)")
    if sys.platform != "darwin":
        raise NotFound("only macOS installs are supported (the defines and the Core library are the Mac ones)")
    return Engine(root.resolve(), _version(root))


def clang() -> tuple[str | None, str]:
    """The C++ compiler, probed (CM12): its path, or None with the reason."""
    exe = shutil.which("clang++")
    if exe is None:
        return None, "clang++ is not on PATH"
    p = resources.run([exe, "--version"], timeout=60, heavy=False)
    if p.returncode != 0:
        return None, f"clang++ --version failed: {(p.stderr or '')[-200:]}"
    return exe, (p.stdout or "").splitlines()[0] if p.stdout else "clang++"


def cache(state_root: Path, eng: Engine) -> Path:
    d = state_root / "unreal" / eng.tag
    d.mkdir(parents=True, exist_ok=True)
    return d


def shadow(eng: Engine, cache_dir: Path) -> Path:
    """The truth build's two platform headers: copies with the vector-intrinsics line set to 0, checked to be the
    only change."""
    root = cache_dir / "shadow"
    for (sub, name), (pattern, line) in SHADOW.items():
        src = eng.core_public / sub / name
        text = src.read_text(encoding="utf-8")
        new, n = re.subn(pattern, line, text, flags=re.M)
        if n != 1:
            raise NotFound(f"{eng.rel(src)}: expected one line matching {pattern!r}, found {n} (a newer engine?)")
        out = root / sub / name
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.is_file() or out.read_text(encoding="utf-8") != new:
            out.write_text(new, encoding="utf-8")
    return root


def flags(eng: Engine, cache_dir: Path, build: str) -> list[str]:
    """Compiler flags for the truth or the shipped build (no -c/-o/-fsyntax-only)."""
    if build not in ("truth", "shipped"):
        raise ValueError(build)
    inc = [eng.core_public, eng.runtime / "Core" / "Internal", eng.runtime / "Core" / "Private",
           eng.runtime / "TraceLog" / "Public", eng.runtime / "AutoRTFM" / "Public"]
    if build == "truth":
        inc = [shadow(eng, cache_dir), *inc]
    fp = ["-ffp-contract=off"]   # as UnrealBuildTool compiles for Mac (MacToolChain.cs): no FMA contraction
    return (["-std=c++20", *fp, *WARNINGS, *[f"-D{d}" for d in DEFINES]] + [f"-I{p}" for p in inc if p.is_dir()])


__all__ = ["Engine", "NotFound", "cache", "clang", "flags", "installs", "locate", "shadow"]
