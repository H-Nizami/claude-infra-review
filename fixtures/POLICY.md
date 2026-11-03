# Infrastructure review policy (fixture)

Rules the reviewer enforces on changes under `fixtures/`. These are the semantic checks that generic scanners cannot make, because they depend on this organisation's context. Approval markers go in the PR description, one per line.

1. **Data residency.** All resources run in `eu-central-1` or `eu-west-1` only. Any change that moves a resource, a provider, or a default region elsewhere is a violation. Removing the guard rail that enforces this (for example the `region` variable validation) also counts.
2. **Stateful resources.** `aws_db_instance`, `aws_s3_bucket` holding data, and PVC-backed StatefulSets must never be replaced or force-destroyed in a normal PR. This covers changes to attributes that force replacement, `force_destroy = true`, and turning off `deletion_protection` or `prevent_destroy`.
3. **Cost.** Any instance class or instance type change that raises the list price per hour by more than 2× needs a `COST-APPROVED:` line in the PR description. Flag it otherwise.
4. **Public exposure.** No internet-facing load balancers and no public buckets without a `PUBLIC-APPROVED:` line in the PR description.
5. **IAM.** No new `*` actions or `*` resources. `iam:PassRole` must be scoped to specific role ARNs.
