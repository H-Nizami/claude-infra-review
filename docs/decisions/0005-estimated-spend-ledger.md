# 0005. Reserve estimated spend and report limits honestly

## Status

Accepted (2026-10-22).

## Context

Subscription authentication does not yield a token invoice. CLI usage fields and
public list prices can support estimates, while missing usage and interrupted
calls must not become free ledger entries. CI runners do not share local state.

## Decision

Commit a $2 estimated-spend ledger split into $1.50 eval and $0.50 CI. Reserve
allowance before each local call, write atomically, and conservatively account for
failed calls and unknown usage. Charge the larger of reported and token-derived
cost. Lower-only command-line budgets cannot silently increase the limit.

Keep CI disabled pending owner activation and opt each PR in. Precharge an exact
head SHA, run ID, and run attempt on the default branch before CI can call Claude.
Use the same ledger lock for local and CI reservation updates. Reconcile any
overrun before the next demo. Label subscription dollar figures as estimates.
Keep unverifiable model prices null.

## Consequences

Preflight prevents a new local call without allowance. If the CLI exceeds its
reservation, stop subsequent calls and preserve the overrun evidence. A strict
external consumption cap cannot be guaranteed when subscription CLI enforcement
is unknown. CI precharges admission to each exact attempt, while local and CI
execution still depend on the CLI respecting its per-call limit. Production
rollout needs a centralized reservation service with automated reconciliation.
