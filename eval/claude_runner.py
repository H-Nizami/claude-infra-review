"""Single, bounded CLI invocation. Importing this module never invokes Claude."""

import json
from pathlib import Path
import subprocess

from .ledger import money
from scripts.validate_findings import validate

TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


class ClaudeFailure(Exception):
    def __init__(self, message, code=1, meta=None):
        super().__init__(message)
        self.code = code
        self.meta = meta


def command(model, turns, budget, schema, prompt):
    return ["claude", "-p", "--output-format", "json", "--model", model,
            "--max-turns", str(turns), "--max-budget-usd", str(budget),
            "--tools", "Read,Grep,Glob", "--allowedTools", "Read,Grep,Glob,StructuredOutput",
            "--disallowedTools", "Bash,Edit,Write,MultiEdit,NotebookEdit,WebFetch,WebSearch,Task,Agent",
            "--permission-mode", "dontAsk", "--setting-sources", "project",
            "--settings", ".claude/settings.json",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--no-session-persistence", "--json-schema",
            json.dumps(schema, separators=(",", ":")), "--", prompt]


def estimate_cost(tokens, pricing, usage=None):
    if not pricing or any(tokens.get(key) is None for key in TOKEN_KEYS):
        return None
    rates = dict(pricing)
    prompt_tokens = sum(tokens[key] for key in TOKEN_KEYS if key != "output_tokens")
    if prompt_tokens > rates.get("long_context_threshold", float("inf")):
        rates.update(rates.get("long_context", {}))
    required = ("input_per_mtok", "output_per_mtok", "cache_write_per_mtok", "cache_read_per_mtok")
    if any(rates.get(key) is None for key in required):
        return None
    # Aggregate CLI usage may omit cache TTL. Reserve the verified 1h rate in that
    # case rather than silently underestimating a 1h write at the cheaper 5m rate.
    cache = (usage or {}).get("cache_creation")
    if not isinstance(cache, dict):
        cache = {}
    short = cache.get("ephemeral_5m_input_tokens")
    long = cache.get("ephemeral_1h_input_tokens")
    cache_tokens = tokens["cache_creation_input_tokens"]
    if type(short) is int and type(long) is int and short >= 0 and long >= 0 and short + long == cache_tokens:
        if long and rates.get("cache_write_1h_per_mtok") is None:
            return None
        cache_cost = money(short) * money(rates["cache_write_per_mtok"]) + money(long) * money(rates.get("cache_write_1h_per_mtok", 0))
    else:
        rate = rates.get("cache_write_1h_per_mtok")
        if cache_tokens and rate is None:
            return None
        cache_cost = money(cache_tokens) * money(rate or 0)
    cost = (money(tokens["input_tokens"]) * money(rates["input_per_mtok"])
            + money(tokens["output_tokens"]) * money(rates["output_per_mtok"])
            + money(tokens["cache_read_input_tokens"]) * money(rates["cache_read_per_mtok"])
            + cache_cost) / money(1000000)
    return float(cost)


def parse_response(stdout, pricing):
    warnings = []
    try:
        response = json.loads(stdout)
        if not isinstance(response, dict):
            raise ValueError()
    except (ValueError, TypeError) as exc:
        raise ClaudeFailure("Claude returned malformed JSON; reservation retained") from exc
    usage = response.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    tokens = {}
    for key in TOKEN_KEYS:
        value = usage.get(key)
        tokens[key] = value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        if tokens[key] is None:
            warnings.append(f"missing or invalid usage.{key}")
    cost = response.get("total_cost_usd")
    try:
        cost = float(money(cost)) if cost is not None else None
    except ValueError:
        cost = None
    if cost is None:
        warnings.append("missing or invalid total_cost_usd")
    turns = response.get("num_turns")
    if not isinstance(turns, int) or isinstance(turns, bool) or turns < 0:
        turns = None
        warnings.append("missing or invalid num_turns")
    if "is_error" not in response:
        warnings.append("missing is_error")
    if "cache_creation" in usage and not isinstance(usage["cache_creation"], dict):
        warnings.append("invalid usage.cache_creation; estimate uses conservative 1h cache rate")
    meta = {"tokens": tokens, "reported_usd": cost, "is_error": response.get("is_error"),
            "est_usd": estimate_cost(tokens, pricing, usage), "num_turns": turns,
            "warnings": warnings, "price": "verified" if pricing else "unverified"}
    if meta["est_usd"] is None:
        meta["price"] = "unverified"
    meta["estimate_method"] = "tokens × verified list price; unknown cache TTL uses 1h rate; aggregate long-context uses higher tier conservatively"
    if response.get("is_error"):
        # Error bodies may contain credentials. Classify but never echo them.
        error = str(response.get("result", "")).lower()
        refused = any(word in error for word in ("auth", "login", "unknown option", "unknown flag", "invalid api key"))
        raise ClaudeFailure("Claude returned an error; no retry", 2 if refused else 1, meta)
    findings = response.get("structured_output")
    if findings is None:
        try:
            findings = json.loads(response.get("result", ""))
        except (TypeError, ValueError) as exc:
            raise ClaudeFailure("Claude omitted structured findings", meta=meta) from exc
    meta["output"] = findings
    return meta


def invoke(workdir, model, turns, budget, schema, prompt, pricing, raw_path):
    try:
        result = subprocess.run(command(model, turns, budget, schema, prompt), cwd=workdir,
                                capture_output=True, text=True, timeout=300, check=False)
    except subprocess.TimeoutExpired as exc:
        # No retry: the process may already have incurred cost.
        raise ClaudeFailure("Claude timed out; reservation retained") from exc
    Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
    Path(raw_path).write_text(result.stdout)
    if result.returncode:
        diagnostic = (result.stderr + result.stdout).lower()
        category = next((label for label, terms in (
            ("filesystem permission", ("permission denied", "operation not permitted", "eacces", "eperm", "read-only file system")),
            ("nested CLI session", ("cannot be launched inside", "nested sessions")),
            ("network connection", ("enotfound", "econnrefused", "fetch failed", "unable to connect")),
            ("model unavailable", ("model not found", "invalid model", "does not exist")),
            ("CLI configuration", ("invalid settings", "invalid json", "unexpected argument")),
            ("hook configuration", ("hook",)),
            ("budget option", ("budget",)),
            ("model option", ("model",)),
            ("tool option", ("tool",)),
        ) if any(term in diagnostic for term in terms)), "unclassified startup error")
        refused = any(word in diagnostic for word in ("auth", "login", "unknown option", "unknown flag", "invalid api key"))
        # Preserve valid usage metadata even when the CLI exits unsuccessfully.
        meta = None
        try:
            meta = parse_response(result.stdout, pricing)
        except ClaudeFailure as failure:
            meta = failure.meta
        # Emit a vocabulary of known error terms, never the raw error body.
        terms = [word for word in ("error", "eacces", "eperm", "settings", "hooks", "onfailure", "budget", "model", "schema", "turns", "output", "argument", "prompt", "stdin", "restricted", "sandbox", "api", "connection", "certificate", "failed", "required", "directory", "config", "mcp") if word in diagnostic]
        raise ClaudeFailure(f"Claude CLI failed: {category} ({','.join(terms)}); no retry (raw output saved)", 2 if refused else 1, meta)
    meta = parse_response(result.stdout, pricing)
    try:
        validate(meta["output"])
    except ValueError as exc:
        raise ClaudeFailure("Claude output failed findings validation", meta=meta) from exc
    return meta
