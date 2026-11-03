# Demo review output

Sticky comment and inline finding posted by the review workflow on a seeded demo pull
request (scenario S07: RDS master username change). The demo change was never merged
and no infrastructure was applied. Structured output: [demo-findings.json](demo-findings.json);
numeric usage: [demo-run-meta.json](demo-run-meta.json).

## Sticky comment

### Infrastructure review

Risk: **high**

One change: the RDS master username on aws\_db\_instance\.orders goes from orders\_admin to orders\_owner\. Changing the master username forces replacement of the instance, which POLICY\.md rule 2 forbids in a normal PR\. deletion\_protection and a final snapshot are set, so the apply would probably be blocked or fail rather than silently destroy data\. The PR still needs a migration plan\. The scanners reported no findings\.

| Severity | File:line | Title | Source |
|---|---|---|---|
| high | fixtures/terraform/main\.tf:169 | RDS master username change forces DB replacement | claude |

<details><summary>Finding details</summary>

**RDS master username change forces DB replacement** — `semantic`

Why: Changing \`username\` on aws\_db\_instance\.orders is a force-new attribute, so the plan replaces the stateful orders database\. POLICY\.md rule 2 forbids replacing aws\_db\_instance in a normal PR\. deletion\_protection and the final snapshot reduce the risk of data loss but do not make the replacement acceptable\.

Fix: Revert the username change to keep the existing instance\. If the rename is really needed, do it as a planned migration: snapshot and restore or use DMS into a new instance, with explicit approval\. Do not change the master username in place\.

</details>

---
Model: claude-sonnet-5-5; turns: 6; tokens in/out: 6/1025.
Estimated cost: 0.036083199999999996 USD (estimate: CLI-reported USD estimate; list-price estimate not calculated; subscription auth is not billed per token).


## Inline finding

**fixtures/terraform/main.tf:169**

<!-- cir:finding:253b3dcf283041fd2e4b0448cc679157e470b1aa -->
**RDS master username change forces DB replacement** — `semantic`

Why: Changing \`username\` on aws\_db\_instance\.orders is a force-new attribute, so the plan replaces the stateful orders database\. POLICY\.md rule 2 forbids replacing aws\_db\_instance in a normal PR\. deletion\_protection and the final snapshot reduce the risk of data loss but do not make the replacement acceptable\.

Fix: Revert the username change to keep the existing instance\. If the rename is really needed, do it as a planned migration: snapshot and restore or use DMS into a new instance, with explicit approval\. Do not change the master username in place\.

