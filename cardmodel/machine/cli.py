"""cli — the machine commands.

  cardmodel emu ROM [--engine lifted|native|host|ir] [--model auto|dmg|cgb] [--port N] [--no-browser]
                    [--save-dir DIR] [--no-save] [--rate HZ] [--relift]
                    [--headless --frames N --input SCRIPT --png F --wav F]
  cardmodel isa build|check|list [ISA] [--samples N] [--seed S] [--engines ir,host,native]
  cardmodel machine survey DIR [--frames N] [--engine E] [--limit N] [--shots DIR]
  cardmodel machine lift ROM [--relift]         lift + compile a ROM's code, print the report
  cardmodel machine diff ROM [--frames N]       lifted vs interpreter, frame by frame (state hashes)
  cardmodel machine info ROM                    the cartridge header, decoded with the cartridge card
  cardmodel machine testroms DIR                run test ROMs, read their verdicts (serial / screen / registers)
  cardmodel machine nds ROM [--frames N] [--lift]   the DS prototype: direct boot, both CPUs, measured coverage;
                                                --lift also lifts the ARM9's ARM code and runs a differential
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _ctx(args):
    from ..cli import _ctx as ctx_of
    return ctx_of(args)


def _out(args, data, text):
    if args.json:
        print(json.dumps(data, indent=1, sort_keys=True, default=str))
    else:
        print(text)


def cmd_emu(args) -> int:
    from . import gb as G
    from . import shell as S
    ctx = _ctx(args)
    say = (lambda m: print(f"[emu] {m}", file=sys.stderr)) if not args.json else (lambda m: None)
    try:
        sess = S.Session(ctx, args.rom, engine=args.engine, model=args.model,
                         save_dir=Path(args.save_dir).expanduser() if args.save_dir else None,
                         sample_rate=args.rate, saves=not args.no_save, progress=say)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    info = sess.info
    if not info["supported"]:
        say(f"the cartridge's controller ({info['mbc']}) is not modelled yet; running it as a plain ROM")
    if sess.rtc_advanced:
        say(f"the clock advanced {sess.rtc_advanced} s since the save")
    if args.headless:
        script = S.parse_input(args.input)
        r = S.run_headless(sess, args.frames, script)
        if args.png:
            Path(args.png).write_bytes(G.png(r["frame"], scale=args.scale))
        if args.wav and r["pcm"]:
            Path(args.wav).write_bytes(G.wav(r["pcm"], sess.gb.sample_rate))
        out = sess.close()
        data = {k: v for k, v in r.items() if k not in ("frame", "pcm")}
        data.update({"title": info["title"], "engine": sess.gb.engine, "cgb": bool(sess.gb.cgb), **out})
        _out(args, data, f"{info['title']} [{sess.gb.engine}{', CGB' if sess.gb.cgb else ''}]: {r['frames']} frames in "
                         f"{r['seconds']} s ({r['speed']}x real time); frame sha1 {r['frame_sha1'][:16]}"
                         + (f"; serial {r['serial']!r}" if r["serial"] else "")
                         + ("; CPU LOCKED" if r["locked"] else ""))
        return 1 if r["locked"] else 0
    S.serve(sess, port=args.port, open_browser=not args.no_browser, log=say)
    return 0


def cmd_isa(args) -> int:
    from . import bench
    from . import isa as I
    ctx = _ctx(args)
    name = args.isa or "lr35902"
    if args.action == "build":
        r = I.build(ctx, name)
        _out(args, r, f"{name}: compiled {r['cards']} instruction cards ({r['ir_changed']} changed)")
        return 0
    if args.action == "list":
        s = I.summary(ctx.store, name)
        _out(args, s, json.dumps(s, indent=1))
        return 0
    sync = I.in_sync(ctx, name)
    engines = args.engines.split(",") if args.engines else None
    r = bench.conformance(ctx, name, engines=engines, seed=args.seed, samples=args.samples)
    bad = {k: v for k, v in r["per_card"].items() if v["status"] != "pass"}
    lines = [f"seed {r['seed']} (reproduce with --seed {r['seed']})",
             f"{name}: {r['passed']}/{r['cards']} instruction cards pass in {', '.join(r['engines'])} "
             f"({r['runs']} one-instruction runs, {r['samples']} samples each); IR in sync: {sync['status']}"]
    if r["unavailable"]:
        lines.append(f"unavailable engines: {r['unavailable']}")
    for k, v in list(bad.items())[:20]:
        lines.append(f"  FAIL {k} {v['mnemonic']}: {'; '.join(v['problems'][:3])}")
    _out(args, {**{k: v for k, v in r.items() if k != "per_card"}, "failing": bad, "sync": sync}, "\n".join(lines))
    return 0 if r["status"] == "pass" and sync["status"] == "pass" else 1


def cmd_machine(args) -> int:
    from . import gb as G
    ctx = _ctx(args)
    if args.action == "info":
        rom, name = G.open_rom(args.target)
        h = G.header(rom, ctx.store)
        _out(args, h, json.dumps(h, indent=1))
        return 0
    if args.action == "survey":
        from . import survey
        shots = Path(args.shots).expanduser() if args.shots else None

        def prog(k, n, row):
            if not args.json:
                print(f"[{k}/{n}] {row['status']:<7} {row['file'][:70]}", file=sys.stderr)

        r = survey.run(ctx, args.target, frames=args.frames, engine=args.engine, limit=args.limit, shots_dir=shots,
                       progress=prog)
        ctx.save_state("emu_survey", {k: v for k, v in r.items()})
        lines = [f"{r['folder_files']} ROMs, {r['frames']} frames each, engine {r['engine']}: {r['counts']} "
                 f"(runs {r['runs_fraction']:.1%}); unsupported mappers {r['unsupported_mappers']}"]
        for row in r["rows"]:
            if row["status"] != "runs":
                lines.append(f"  {row['status']:<7} {row['file'][:60]:<60} {row.get('mbc')} — {row.get('reason')}")
        _out(args, {k: v for k, v in r.items() if k != "rows"}, "\n".join(lines))
        return 0
    if args.action == "lift":
        from . import lift
        rom, name = G.open_rom(args.target)
        m, rep = lift.lifted_machine(ctx, rom, relift=args.relift,
                                     progress=lambda msg: print(f"[lift] {msg}", file=sys.stderr))
        _out(args, rep, json.dumps(rep, indent=1))
        return 0
    if args.action == "diff":
        from . import diff
        rom, name = G.open_rom(args.target)
        r = diff.differential(ctx, rom, frames=args.frames)
        import hashlib
        diffs = ctx.load_state("emu_diffs") or {}
        diffs[hashlib.sha1(rom).hexdigest()[:16]] = {k: r[k] for k in ("verdict", "frames_compared",
                                                                       "first_difference", "speedup", "blocks")}
        ctx.save_state("emu_diffs", diffs)
        _out(args, r, f"{name}: {r['verdict']} over {r['frames_compared']} frames"
                      + (f" (first difference at frame {r['first_difference']})" if r.get("first_difference") is not None
                         else "") + f"; interpreter {r['interp_s']} s, lifted {r['lifted_s']} s "
                                    f"({r['speedup']}x); {r['blocks']} blocks")
        return 0 if r["verdict"] == "identical" else 1
    if args.action == "nds":
        from . import nds
        rom = nds.open_nds(args.target)
        try:
            ds = nds.DS(ctx, rom, engine=args.engine)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        secs = ds.run(args.frames)
        cov = nds.coverage(ds)
        cov["seconds"] = round(secs, 2)
        if args.lift:
            from . import lift_arm
            cov["lifted_differential"] = lift_arm.differential(ctx, rom, args.frames, args.frames)
        ctx.save_state("nds_coverage", cov)
        lines = [f"{cov['title']} ({cov['game_code']}): {cov['frames']} frames in {cov['seconds']} s, "
                 f"{cov['instruction_cards']} ARM/Thumb instruction cards"]
        for name, c in cov["cpus"].items():
            why = "stopped at an undefined instruction" if c["stopped"] else ("halted" if c["halted"] else "running")
            lines.append(f"  {name}: {c['instructions_executed']:,} instructions, {c['distinct_instruction_addresses']:,} "
                         f"distinct, {c['cards_used']} cards used, {c['undecodable_executed']} undecodable; now at "
                         f"{c['pc']} ({c['state']}, mode {c['mode']}, {why})")
            lines.append(f"     BIOS calls {c['swi_calls']} (not modelled: {c['swi_unmodelled'] or 'none'})")
            lines.append(f"     touched but not modelled: {c['unmodelled_hardware_touched'] or 'nothing'}")
        if "lifted_differential" in cov:
            d = cov["lifted_differential"]
            lines.append(f"  lifted ARM9 code: {d['blocks']} blocks ({d['instructions_lifted']} instructions); "
                         f"{d['verdict']} to the interpreter over {d['frames_compared']} frames; "
                         f"{d['block_runs']:,} block runs; {d['speedup']}x")
        _out(args, cov, "\n".join(lines))
        return 0 if cov.get("lifted_differential", {}).get("verdict", "identical") == "identical" else 1
    if args.action == "testroms":
        from . import testroms
        r = testroms.run(ctx, args.target, engine=args.engine)
        lines = [f"{r['passed']}/{r['total']} test ROMs pass ({r['engine']}); {r['skipped']} skipped (other "
                 f"hardware or not self-checking)"]
        lines += [f"  {k}: {v['passed']}/{v['total']}" for k, v in r["suites"].items()]
        for row in sorted(r["rows"], key=lambda x: (x["verdict"] == "pass", x["verdict"] == "skipped")):
            lines.append(f"  {row['verdict']:<8} {row.get('model', '-'):<4} {row['file']}  "
                         f"{row.get('detail', '')[:110]}")
        ctx.save_state("emu_testroms", r)
        _out(args, r, "\n".join(lines))
        return 0 if r["total"] and r["passed"] == r["total"] else 1
    return 2


def register(sub) -> None:
    s = sub.add_parser("emu", help="run a Game Boy / Game Boy Color ROM through the card model")
    s.add_argument("rom")
    s.add_argument("--engine", default="lifted", help="lifted (default), native, host (Python) or ir (reference)")
    s.add_argument("--model", default="auto", choices=["auto", "dmg", "cgb"])
    s.add_argument("--port", type=int, default=0); s.add_argument("--no-browser", action="store_true")
    s.add_argument("--save-dir"); s.add_argument("--no-save", action="store_true")
    s.add_argument("--rate", type=int, default=48000, help="audio sample rate (0 = no audio)")
    s.add_argument("--headless", action="store_true"); s.add_argument("--frames", type=int, default=600)
    s.add_argument("--input", help="headless input script, e.g. '60:start,66:-,120:a+right'")
    s.add_argument("--png"); s.add_argument("--wav"); s.add_argument("--scale", type=int, default=2)
    s.set_defaults(fn=cmd_emu)
    s = sub.add_parser("isa", help="instruction cards: build their IR, check them in every engine, list them")
    s.add_argument("action", choices=["build", "check", "list"]); s.add_argument("isa", nargs="?")
    s.add_argument("--samples", type=int, default=8); s.add_argument("--seed", type=int); s.add_argument("--engines")
    s.set_defaults(fn=cmd_isa)
    s = sub.add_parser("machine", help="machines: survey ROMs, lift a ROM, differential runs, test ROMs")
    s.add_argument("action", choices=["survey", "lift", "diff", "info", "testroms", "nds"]); s.add_argument("target")
    s.add_argument("--frames", type=int, default=1200); s.add_argument("--engine", default="native")
    s.add_argument("--limit", type=int); s.add_argument("--shots"); s.add_argument("--relift", action="store_true")
    s.add_argument("--lift", action="store_true", help="nds: also lift the ARM9's code and run a differential")
    s.set_defaults(fn=cmd_machine)


__all__ = ["register"]
