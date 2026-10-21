"""cli — `cardmodel cycle`: the model running, checking and improving itself as one unit.

  cardmodel cycle run [--profile quick|standard|full] [--record] [--record-verdicts] [--commit]
                      [--stages a,b] [--seed N] [--budget S] [--write FILE]
  cardmodel cycle report [--write FILE]          the last cycle's weakness report (WEAKNESSES.md with --record)
  cardmodel cycle status                         the last cycles, a running one, when the next automatic one is due
  cardmodel cycle ledger [--accept --reason R] [--additions]   the core ledger: what is protected, what changed
  cardmodel cycle schedule [--install | --uninstall] [--every HOURS | --at HH:MM] [--profile P] [--record]
                           [--commit]            run a profile on a timer (launchd on macOS; a cron line elsewhere)
  cardmodel cycle auto on|off                    whether using the model starts cycles in the background

Exit status: 0 pass, 1 the cycle found critical or high problems (or the ledger is broken), 2 bad input,
3 another cycle is running.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ..kernel import paths


def _out(args, data, text):
    if args.json:
        print(json.dumps(data, indent=1, sort_keys=True, default=str))
    else:
        print(text)


def cmd_cycle(args) -> int:
    from . import hook, ledger
    from . import run as R
    if args.action == "run":
        say = (lambda m: print(m, file=sys.stderr, flush=True)) if not args.json else (lambda m: None)
        stages = args.stages.split(",") if args.stages else None
        try:
            out = R.run(profile=args.profile, record=args.record, record_verdicts=args.record_verdicts, stages=stages,
                        seed=args.seed, budget_s=args.budget, commit_changes=args.commit, auto=args.auto, say=say,
                        write=args.write)
        except R.Busy as exc:
            print(f"another cycle is running: {exc}", file=sys.stderr)
            return 3
        except (ValueError, KeyError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if out.get("status") == "skipped":
            _out(args, out, f"cycle skipped: {out.get('reason')}")
            return 0
        an = out["analysis"]
        lines = [f"cycle {out['status']} · profile {out['profile']} · seed {out['seed']} · "
                 f"{out['seconds']:.0f} s · " + ", ".join(f"{n} {s}" for s, n in an["counts"].items() if n)
                 + f" · {an['regressions']} regression(s)"]
        for name, r in out["stages"].items():
            lines.append(f"  {name:<9} {r.get('status', '?'):<8} {str(r.get('summary', ''))[:150]}  "
                         f"[{r.get('seconds')}s]")
        top = [x for x in an["findings"] if x["severity"] in ("critical", "high")][:12]
        for x in top:
            lines.append(f"  {x['severity'].upper():<8} {x['item']}: {x['message'][:220]}")
        if out.get("written"):
            lines.append("wrote " + ", ".join(out["written"]))
        if out.get("commit"):
            c = out["commit"]
            lines.append(f"committed {c['commit']} ({c['files']} files)" if c.get("committed") else
                         f"not committed: {c.get('reason')}")
        lines.append(f"report: {R.cycle_dir(R.model_ctx()) / 'report.md'} (cardmodel cycle report)")
        _out(args, {k: v for k, v in out.items() if k != "shortfalls"}, "\n".join(lines))
        return 0 if out["status"] == "pass" else 1
    if args.action == "report":
        ctx = R.model_ctx()
        p = R.cycle_dir(ctx) / "report.md"
        if not p.is_file():
            print("no cycle has run here yet: cardmodel cycle run", file=sys.stderr)
            return 2
        text = p.read_text(encoding="utf-8")
        if args.write:
            Path(args.write).write_text(text, encoding="utf-8")
            text = f"wrote {args.write}"
        if args.json:
            print(json.dumps(R.load_last(R.cycle_dir(ctx)) or {}, indent=1, sort_keys=True, default=str))
        else:
            print(text)
        return 0
    if args.action == "status":
        ctx = R.model_ctx()
        d = R.cycle_dir(ctx)
        hist = (d / "history.jsonl").read_text(encoding="utf-8").splitlines() if (d / "history.jsonl").is_file() else []
        rows = [json.loads(x) for x in hist[-10:]]
        auto = json.loads((d / "auto.json").read_text(encoding="utf-8")) if (d / "auto.json").is_file() else {}
        cfg = R.config(ctx).get("auto") or {}
        busy = R.running()
        go, why = hook.decide(args, paths.home())
        nxt = float(auto.get("last_start") or 0) + float(cfg.get("min_interval_s", 3600))
        data = {"runs": rows, "running": busy, "auto": auto, "auto_now": go, "auto_why": why,
                "schedule_installed": hook.agent_path().exists()}
        lines = [f"{'running now: ' + json.dumps(busy) if busy else 'no cycle running'}",
                 f"automatic cycles: {'off' if auto.get('disabled') else 'on'} (profile {cfg.get('profile')}, at most "
                 f"every {int(cfg.get('min_interval_s', 3600)) // 60} min); next possible "
                 + (time.strftime('%Y-%m-%d %H:%M', time.localtime(nxt)) if nxt > time.time() else "now")
                 + f"; a command run now would {'start one' if go else 'not start one: ' + why}",
                 "schedule: " + (f"installed ({hook.agent_path()})" if data["schedule_installed"] else "not installed"),
                 "", "recent cycles:"]
        for r in rows:
            c = r.get("counts") or {}
            lines.append(f"  {r['started'][:16]} {r['profile']:<8} {r['status']:<5} {r['seconds']:>6.0f} s  "
                         f"critical {c.get('critical', 0)} high {c.get('high', 0)} medium {c.get('medium', 0)}  "
                         f"regressions {r.get('regressions', 0)}" + ("  (auto)" if r.get("auto") else ""))
        if not rows:
            lines.append("  none yet (cardmodel cycle run)")
        _out(args, data, "\n".join(lines))
        return 0
    if args.action == "ledger":
        ctx = R.model_ctx()
        if args.accept or args.additions:
            try:
                res = ledger.accept(ctx, reason=args.reason, additions_only=args.additions and not args.accept,
                                    layer="model")
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            _out(args, res, f"ledger {'updated' if res['changed'] else 'unchanged'}: {res['protected']}; grown "
                            f"{res['grown']}, amended {res['amended']}" + (f", still failing {res['still_failing']}"
                                                                           if res.get("still_failing") else ""))
            return 0
        r = ledger.check(ctx)
        lines = [f"core ledger: {r['status']}" + (f" ({r.get('reason')})" if r.get("reason") else ""),
                 f"  protected {r.get('protected') or {}}; accepted {r.get('accepted')}; "
                 f"{r.get('amendments', 0)} amendment(s)"]
        for kind in ledger.KINDS:
            for x in r.get(kind) or []:
                lines.append(f"  {kind:<12} {x['item']}" + (f": {x['detail']}" if x.get("detail") else ""))
        _out(args, r, "\n".join(lines))
        return 1 if r["status"] == "fail" else 0
    if args.action == "schedule":
        home = paths.home()
        if args.uninstall:
            res = hook.uninstall()
            _out(args, res, f"{'removed' if res['removed'] else 'nothing to remove'}: {res['path']}")
            return 0
        if sys.platform != "darwin":
            line = hook.cron_line(home, args.profile or "full", args.record, args.commit, args.every, args.at)
            _out(args, {"cron": line}, "add this line with `crontab -e` (nothing was installed):\n" + line)
            return 0
        data = hook.plist(home, args.profile or "full", args.record, args.commit, args.every, args.at)
        if not args.install:
            _out(args, {"plist": data.decode(), "path": str(hook.agent_path())},
                 f"would install {hook.agent_path()} (run again with --install):\n" + data.decode())
            return 0
        res = hook.install(data)
        _out(args, res, f"installed {res['path']}; loaded: {res['loaded']} {res.get('detail') or ''}".rstrip())
        return 0 if res["loaded"] else 1
    if args.action == "auto":
        if args.target not in ("on", "off"):
            print("error: cardmodel cycle auto on|off", file=sys.stderr)
            return 2
        st = hook.set_auto(paths.home(), args.target == "on")
        _out(args, st, f"automatic cycles {'on' if not st['disabled'] else 'off'} for {paths.home()}")
        return 0
    return 2


def register(sub) -> None:
    s = sub.add_parser("cycle", help="the model as one unit: run every part, find weaknesses, keep the core, improve")
    s.add_argument("action", choices=["run", "report", "status", "ledger", "schedule", "auto"])
    s.add_argument("target", nargs="?", help="auto: on or off")
    s.add_argument("--profile", choices=["quick", "standard", "full"])
    s.add_argument("--record", action="store_true", help="run: write lasting evidence (ledger growth, learned "
                                                         "cards, generated documents, WEAKNESSES.md)")
    s.add_argument("--record-verdicts", action="store_true", help="run: also write verify's verdicts into cards")
    s.add_argument("--commit", action="store_true", help="run/schedule: commit what the cycle wrote (local only)")
    s.add_argument("--stages", help="run: only these stages, comma-separated")
    s.add_argument("--seed", type=int)
    s.add_argument("--budget", type=float, help="run: seconds (default: the profile's budget)")
    s.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)
    s.add_argument("--write", help="run/report: write the report to this file")
    s.add_argument("--accept", action="store_true", help="ledger: write the model's core into the ledger")
    s.add_argument("--additions", action="store_true", help="ledger: accept only growth (nothing lost or weakened)")
    s.add_argument("--reason", help="ledger: why something was lost, changed or weakened")
    s.add_argument("--install", action="store_true", help="schedule: install the launchd agent")
    s.add_argument("--uninstall", action="store_true", help="schedule: remove the launchd agent")
    s.add_argument("--every", type=float, default=6, help="schedule: hours between runs (default 6)")
    s.add_argument("--at", help="schedule: a daily time HH:MM instead of --every")
    s.set_defaults(fn=cmd_cycle)


__all__ = ["cmd_cycle", "register"]
