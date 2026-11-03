#!/usr/bin/env python3
"""Evaluate seeded patches offline; paid model calls require a separate opt-in."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from eval.claude_runner import ClaudeFailure, invoke  # noqa: E402
from eval.ledger import BudgetStop, Ledger, money  # noqa: E402
from eval.scoring import predictions, score  # noqa: E402


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--scenarios", default="all")
    result.add_argument("--with-claude", action="store_true")
    result.add_argument("--model", default="claude-sonnet-5-5")
    result.add_argument("--max-turns", type=int, default=6)
    result.add_argument("--per-run-usd", default="0.12")
    result.add_argument("--budget-usd")
    result.add_argument("--runs", type=int, default=1)
    result.add_argument("--out", type=Path, default=Path("eval/results"))
    result.add_argument("--keep-workdirs", action="store_true")
    result.add_argument("--ledger", type=Path, help="Alternate ledger (for isolated rehearsals)")
    ledger = result.add_mutually_exclusive_group()
    ledger.add_argument("--ledger-add")
    ledger.add_argument("--ledger-show", action="store_true")
    result.add_argument("--note", default="")
    return result


def git(workdir, *args):
    return subprocess.run(["git", "-c", "user.name=eval", "-c", "user.email=eval@localhost",
                           "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                           "-c", "gc.auto=0", "-c", "maintenance.auto=false",
                           *args], cwd=workdir, check=True, capture_output=True, text=True).stdout


def copy_inputs(root, target):
    for name in ("fixtures", ".claude", "CLAUDE.md", "prompts", "schema", "scanners"):
        source = root / name
        if source.is_dir():
            shutil.copytree(source, target / name,
                            ignore=shutil.ignore_patterns(".terraform", "__pycache__"))
        elif source.is_file():
            shutil.copy2(source, target / name)


def scan(root, target, output):
    output.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run([str(root / "scripts/scan.sh"), str(target), str(output)],
                               capture_output=True, text=True, check=False)
    # Diagnostics stay with temporary raw scan data, outside committed summaries.
    (output / "scanner.stdout.log").write_text(completed.stdout)
    (output / "scanner.stderr.log").write_text(completed.stderr)
    if completed.returncode:
        raise RuntimeError("scanner pipeline failed (run scripts/scan.sh directly for diagnostics)")
    findings = json.loads((output / "normalized.json").read_text())
    versions = json.loads((output / "tool-versions.json").read_text())
    if not isinstance(findings, list):
        raise ValueError("normalized scanner output must be an array")
    return findings, versions


def finding_key(finding):
    return tuple(finding[key] for key in ("tool", "rule_id", "file", "line_start"))


def delta_findings(post, baseline):
    base_keys = {finding_key(finding) for finding in baseline}
    return sorted((finding for finding in post if finding_key(finding) not in base_keys),
                  key=lambda f: (f["file"], f["line_start"], f["tool"], f["rule_id"]))


def load_scenarios(root, selection):
    rows = []
    for path in sorted((root / "scenarios").glob("*/answer.yaml"),
                       key=lambda p: (p.parent.name.startswith("N"), p.parent.name)):
        answer = yaml.safe_load(path.read_text())
        rows.append((path.parent, answer))
    requested = None if selection == "all" else set(selection.split(","))
    if requested is not None:
        unknown = requested - {answer["id"] for _, answer in rows}
        if unknown:
            raise ValueError("unknown scenario IDs: " + ", ".join(sorted(unknown)))
        rows = [(path, answer) for path, answer in rows if answer["id"] in requested]
    if not rows:
        raise ValueError("no scenarios selected")
    return rows


def totals(rows, system):
    measured = [row for row in rows if row.get(system) is not None]
    positive = [row for row in measured if row["kind"] == "positive"]
    semantic = [item for row in measured for item in row["semantic_only"][system]]
    return {"tp": sum(row[system]["tp"] for row in measured),
            "fp": sum(row[system]["fp"] for row in measured),
            "fn": sum(row[system]["fn"] for row in measured),
            "detected": sum(row[system]["detected"] for row in positive),
            "positive_scenarios": len(positive), "evaluated_scenarios": len(measured),
            "negative_fp": sum(row[system]["fp"] for row in measured if row["kind"] == "negative"),
            "semantic_only": {"tp": sum(item["detected"] for item in semantic),
                              "fn": sum(not item["detected"] for item in semantic)},
            "prompt_injection_detected": sum(row[system]["prompt_injection_detected"] for row in measured)}


def escape_cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def triple(value):
    return "—" if value is None else f"{value['tp']}/{value['fp']}/{value['fn']}"


def write_reports(output, result, stamp, model):
    output.mkdir(parents=True, exist_ok=True)
    mode = "claude-" + model if result["config"]["with_claude"] else "scanners"
    destination = output / f"{stamp}-{mode}.json"
    destination.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    scanners = result["totals"]["scanners"]
    claude = result["totals"]["claude"]
    lines = ["# Seeded review evaluation", "", f"Status: {result['status']}. Runs per scenario: {result['config']['runs']}.", "",
             "| ID | Title | Kind | Scanners TP/FP/FN | Claude TP/FP/FN | Turns | Tokens in/out | Est $ |",
             "|---|---|---|---|---|---|---|---|"]
    for row in result["scenarios"]:
        meta = row.get("call") or {}
        tokens = meta.get("tokens", {})
        estimate = meta.get("est_usd")
        amount = ("price: unverified (estimate unavailable)" if meta else "—") if estimate is None else f"{estimate:.6f} (estimate)"
        lines.append("| " + " | ".join(escape_cell(value) for value in (
            row["id"], row["title"], row["kind"], triple(row["scanners"]), triple(row.get("claude")),
            meta.get("num_turns", "—"), f"{tokens.get('input_tokens', '—')}/{tokens.get('output_tokens', '—')}", amount)) + " |")
    headline = f"Scanners alone caught {scanners['detected']}/{scanners['positive_scenarios']} seeded misconfigs"
    if claude["evaluated_scenarios"]:
        calls = [row["call"] for row in result["scenarios"] if row.get("call")]
        estimates = [call.get("est_usd") for call in calls]
        cost = (f"${sum(estimates) / len(estimates):.6f} per PR (estimated: tokens × list price)"
                if estimates and all(value is not None for value in estimates)
                else "cost unavailable (estimate: list price or usage unverified)")
        headline += f"; with Claude {claude['detected']}/{claude['positive_scenarios']}, with {claude['fp']} false positives, at {cost}."
    else:
        headline += "; Claude: not run."
    lines += ["", headline, "", "Prompt-injection items are scored separately from scenario detection.",
              f"Negative-control false positives: scanners={scanners['negative_fp']}; Claude={claude['negative_fp']}.",
              f"Semantic-only items TP/FN: scanners={scanners['semantic_only']['tp']}/{scanners['semantic_only']['fn']}; Claude={claude['semantic_only']['tp']}/{claude['semantic_only']['fn']}.",
              "", "## Scanner predictions versus observations", "",
              "| Item | Prediction | Observed | Mismatch |", "|---|---|---|---|"]
    for row in result["scenarios"]:
        for item in row["scanner_predictions"]:
            lines.append(f"| {item['expected_id']} | {item['prediction']} | {'yes' if item['observed'] else 'no'} | {'yes' if item['mismatch'] else 'no'} |")
    for warning in result.get("warnings", []):
        lines += ["", "Warning: " + escape_cell(warning)]
    (output / "latest.md").write_text("\n".join(lines) + "\n")
    (output / "headline.txt").write_text(headline + "\n")
    return destination


def cost_line(scenario, model, meta, ledger):
    snapshot = ledger.snapshot()
    tokens = meta.get("tokens", {})
    def token_text(key):
        value = tokens.get(key)
        return "?" if value is None else f"{value / 1000:.1f}k"
    estimate = meta.get("est_usd")
    text = "unknown" if estimate is None else f"${estimate:.6f}"
    explanation = "tokens × list price" if estimate is not None else "list price or usage unverified; conservative ledger charge"
    print(f"[{scenario}] {model} turns={meta.get('num_turns', '?')} in={token_text('input_tokens')} "
          f"out={token_text('output_tokens')} est={text} (estimate: {explanation}) "
          f"cumulative=${snapshot['spent']:.6f} / ${snapshot['eval_cap']:.2f} eval cap "
          f"(${snapshot['total_cap']:.2f} total)", flush=True)


def main(argv=None, root=ROOT):
    args = parser().parse_args(argv)
    # Refuse before scanning, checking auth, or invoking even `claude --help`.
    if args.with_claude and os.environ.get("CIR_ALLOW_CLAUDE") != "1":
        print("refused: --with-claude requires CIR_ALLOW_CLAUDE=1", file=sys.stderr)
        return 2
    if args.with_claude and os.environ.get("CIR_ALLOW_DOCS_WRITES") == "1":
        print("refused: unset CIR_ALLOW_DOCS_WRITES for the read-only eval", file=sys.stderr)
        return 2
    work = None
    result = None
    status = 0
    output = args.out if args.out.is_absolute() else root / args.out
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        if args.runs < 1 or args.max_turns < 1 or not money(args.per_run_usd):
            raise ValueError("runs, max-turns, and per-run-usd must be positive")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.model):
            raise ValueError("model must be a model identifier")
        ledger = Ledger(args.ledger or root / "eval/spend-ledger.json", args.budget_usd)
        if args.ledger_show:
            print(json.dumps(ledger.snapshot(), indent=2))
            return 0
        if args.ledger_add is not None:
            ledger.add(args.ledger_add, args.note)
            print("CI cost added (estimate).")
            return 0
        selected = load_scenarios(root, args.scenarios)
        pricing = yaml.safe_load((root / "eval/pricing.yaml").read_text())
        price = pricing.get(args.model)
        schema = json.loads((root / "schema/findings.schema.json").read_text()) if args.with_claude else None
        prompt_template = (root / "prompts/review.md").read_text() if args.with_claude else None
        result = {"generated_at": datetime.now(timezone.utc).isoformat(), "status": "incomplete",
                  "config": {"scenarios": [a["id"] for _, a in selected], "runs": args.runs,
                             "with_claude": args.with_claude, "model": args.model if args.with_claude else None,
                             "max_turns": args.max_turns, "per_run_usd": float(money(args.per_run_usd)),
                             "budget_usd": None if args.budget_usd is None else float(money(args.budget_usd))},
                  "pricing": price if args.with_claude else None,
                  "tool_versions": {}, "scenarios": [], "warnings": []}
        if args.with_claude:
            # Presence only; existing CLI login is also supported. Never inspect auth files.
            oauth_present = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
            if not shutil.which("claude"):
                raise ClaudeFailure("Claude executable not found; existing login or OAuth presence required", 2)
            del oauth_present
            if args.model == "claude-haiku-5-5":
                history = [e for e in ledger.snapshot()["entries"] if e.get("model") == "claude-sonnet-5-5"]
                from eval.ledger import entry_cost
                estimate = sum(float(entry_cost(e)) for e in history) / len(history) if history else None
                if estimate is None or estimate * len(selected) * args.runs > ledger.snapshot()["remaining"]:
                    result["warnings"].append("skipped: insufficient budget (no affordable Sonnet comparison)")
                    raise BudgetStop("skipped: insufficient budget")
        work = Path(tempfile.mkdtemp(prefix="cir-eval-"))
        baseline = work / "baseline"
        baseline.mkdir()
        copy_inputs(root, baseline)
        git(baseline, "init", "--quiet")
        git(baseline, "add", ".")
        git(baseline, "commit", "--quiet", "-m", "Eval fixture baseline")
        baseline_findings, versions = scan(root, baseline, work / "scan-baseline")
        result["tool_versions"] = versions
        for attempt in range(1, args.runs + 1):
            for scenario_path, answer in selected:
                scenario_id = answer["id"]
                target = work / f"{attempt}-{scenario_id}"
                target.mkdir()
                copy_inputs(root, target)
                git(target, "init", "--quiet")
                git(target, "add", ".")
                git(target, "commit", "--quiet", "-m", "Eval fixture baseline")
                git(target, "apply", str(scenario_path / "patch.diff"))
                git(target, "add", "fixtures")
                git(target, "commit", "--quiet", "-m", f"Eval scenario {scenario_id}")
                inputs = target / "cir-input"
                inputs.mkdir()
                (inputs / "pr.diff").write_text(git(target, "diff", "HEAD~1"))
                post, _ = scan(root, target, inputs / "scan")
                findings = delta_findings(post, baseline_findings)
                (inputs / "scan/normalized.json").write_text(json.dumps(findings, sort_keys=True) + "\n")
                row = {"id": scenario_id, "run": attempt, "title": answer["title"], "kind": answer["kind"],
                       "scanners": score(findings, answer["expected"]), "scanner_findings": findings,
                       "claude": None, "scanner_predictions": predictions(findings, answer["expected"]),
                       "semantic_only": {"scanners": [{"expected_id": e["id"], "detected": bool(score(findings, [e])["tp"])}
                                                        for e in answer["expected"] if e.get("semantic_only") and e["category"] != "prompt_injection"], "claude": []}}
                result["scenarios"].append(row)
                print(f"[{scenario_id}] scanners TP/FP/FN="
                      f"{row['scanners']['tp']}/{row['scanners']['fp']}/{row['scanners']['fn']}",
                      file=sys.stderr, flush=True)
                if not args.with_claude:
                    continue
                reservation, reserve = ledger.reserve(scenario_id, args.model, args.per_run_usd)
                prompt = prompt_template.replace("{{PR_NUMBER}}", "0").replace("{{BASE_SHA}}", git(target, "rev-parse", "HEAD~1").strip()).replace("{{HEAD_SHA}}", git(target, "rev-parse", "HEAD").strip())
                meta = {}
                failure = None
                try:
                    # Observed overruns enlarge the ledger reservation, never the
                    # user-selected per-call CLI allowance.
                    allowance = min(float(money(args.per_run_usd)), reserve)
                    meta = invoke(target, args.model, args.max_turns, allowance, schema, prompt, price,
                                  output / "raw" / stamp / f"{attempt}-{scenario_id}.json")
                except ClaudeFailure as exc:
                    meta = exc.meta or {}
                    failure = exc
                except (OSError, ValueError) as exc:
                    failure = ClaudeFailure("Claude invocation failed; reservation retained")
                except KeyboardInterrupt:
                    failure = ClaudeFailure("Claude invocation interrupted; reservation retained")
                finally:
                    charge = ledger.settle(reservation, meta.get("tokens", {}), meta.get("est_usd"),
                                           meta.get("reported_usd"), "failed" if failure else "complete")
                    row["call"] = {key: value for key, value in meta.items() if key != "output"}
                    row["call"]["charged_usd"] = charge
                    cost_line(scenario_id, args.model, meta, ledger)
                if failure:
                    row["error"] = str(failure)
                    row["claude"] = score([], answer["expected"])
                    row["semantic_only"]["claude"] = [{"expected_id": e["id"], "detected": False}
                                                         for e in answer["expected"] if e.get("semantic_only") and e["category"] != "prompt_injection"]
                    raise failure
                row["claude_findings"] = meta["output"]
                row["claude"] = score(meta["output"]["findings"], answer["expected"])
                row["semantic_only"]["claude"] = [{"expected_id": e["id"], "detected": bool(score(meta["output"]["findings"], [e])["tp"])}
                                                     for e in answer["expected"] if e.get("semantic_only") and e["category"] != "prompt_injection"]
                if charge > reserve:
                    result["warnings"].append(f"{scenario_id}: CLI cost exceeded its reservation; later calls reserve at least the observed cost")
                if ledger.snapshot()["spent"] > ledger.snapshot()["total_cap"] or ledger.snapshot()["eval_spent"] > ledger.snapshot()["eval_cap"]:
                    raise BudgetStop("CLI exceeded its supplied budget; further calls blocked")
        result["status"] = "complete"
    except BudgetStop as exc:
        status = 3
        if result is not None:
            result["status"] = "budget_stop"
            result["warnings"].append(str(exc))
        print(str(exc), file=sys.stderr)
    except ClaudeFailure as exc:
        status = exc.code
        if result is not None:
            result["status"] = "refused" if status == 2 else "failed"
            result["warnings"].append(str(exc))
        print(str(exc), file=sys.stderr)
    except KeyboardInterrupt:
        status = 130
        if result is not None:
            result["status"] = "interrupted"
            result["warnings"].append("Evaluation interrupted; results are partial.")
        print("eval interrupted: partial results saved", file=sys.stderr)
    except (ValueError, OSError, KeyError, RuntimeError, subprocess.SubprocessError, yaml.YAMLError) as exc:
        status = 1
        if result is not None:
            result["status"] = "failed"
        # Avoid echoing subprocess output or environment values in errors.
        print(f"eval error: {type(exc).__name__}: check inputs and scanner installation", file=sys.stderr)
    finally:
        if result is not None:
            result["totals"] = {system: totals(result["scenarios"], system) for system in ("scanners", "claude")}
            write_reports(output, result, stamp, args.model)
        if work is not None:
            if args.keep_workdirs:
                print(f"Workdirs retained: {work}")
            else:
                shutil.rmtree(work)
    return status


if __name__ == "__main__":
    sys.exit(main())
