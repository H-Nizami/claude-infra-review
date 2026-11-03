# 0003. Scanners first, with auditable model deduplication

## Status

Accepted (2026-10-22).

## Context

Scanners reliably detect many local configuration errors. Policy violations such
as residency, replacement intent, and cost changes also need context. Model-only
review loses deterministic evidence and can quietly suppress a real issue.

## Decision

Run pinned scanners, normalize their findings, and give that evidence to the
read-only reviewer. Require a final finding or a documented drop for each scanner
finding. Score scanner and final model findings separately against fixed scenario
answers. Scanner predictions remain historical hypotheses after runs.

## Consequences

False negatives from model deduplication remain visible. An empty scanner result
does not prove safety. Check failures and malformed outputs are errors, and the
headline stays pending until actual eval results support it.
