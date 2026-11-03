# Two-minute demonstration

Start with the [architecture cover](img/architecture.png): scanners produce
evidence, a read-only model produces validated JSON, and a separate deterministic
job posts it. Only the poster has PR comment permission.

Open [the evaluation](../eval/results/latest.md). The fixed answer keys cover 14
positive scenarios and two negative controls. Scanners detect 7/14; Claude detects
14/14, with three unmatched findings and zero findings on the negative controls.
The injection attempt is reported separately. Average cost is $0.043785 per review
(estimate from token counts and list prices, not a subscription invoice).

Open the [demo review output](examples/demo-comment.md). A seeded demo PR made a
single fixture change to the database master username. The pinned provider marks
that attribute ForceNew. Scanners return no finding, while the model identifies the
stateful replacement risk. The live review workflow passed all three jobs, updated
one sticky comment and posted one inline finding at line 169. Its CLI-reported cost
was $0.0360832 (estimate). The demo change is intentionally risky and is never
merged; no infrastructure is applied.

Show the review workflow's permissions: Claude has a read-only GitHub token and
Read/Grep/Glob tools. Its internal StructuredOutput tool only delivers JSON. The
poster validates and escapes that JSON, updates one sticky comment, and adds
deduplicated inline findings only on actual diff lines.

Finish with the [playbook](playbook.md) and [spend ledger](../eval/spend-ledger.json).
Calls need estimated-spend allowance before starting. CI needs a precharged exact
run attempt; secrets stay in the Claude job. Failed startup attempts and unused
conservative reservations remain visible. These controls cannot undo usage if the
CLI overruns its supplied limit.

## Reproduce without model spend

Follow the README quickstart, then run:

```bash
scripts/scan.sh . /tmp/cir-demo-baseline
python3 eval/run.py --scenarios all --out .cache/demo-scanners
make lint test diagram
```

Use a separate `--out` directory for a scanners-only replay so the published live
headline and report remain together. Live reruns require owner approval and must
fit the remaining ledger allowance.
