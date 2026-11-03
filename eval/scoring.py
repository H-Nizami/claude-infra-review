"""Pure scoring functions; answer keys describe post-patch source locations."""

SEVERITY = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def matches(finding, expected, tolerance=3):
    start, end = expected["lines"]
    return (
        finding["file"] == expected["file"]
        and finding["line_start"] <= end + tolerance
        and finding["line_end"] >= start - tolerance
        and finding["category"] in (expected["category"], "other")
        and SEVERITY[finding["severity"]] >= SEVERITY[expected["min_severity"]]
    )


def score(findings, expected):
    pairs = [
        {"expected_id": item["id"], "finding_index": index}
        for item in expected
        for index, finding in enumerate(findings)
        if matches(finding, item)
    ]
    hit_ids = {pair["expected_id"] for pair in pairs}
    hit_findings = {pair["finding_index"] for pair in pairs}
    required = [item for item in expected if item["category"] != "prompt_injection"
                and SEVERITY[item["min_severity"]] >= SEVERITY["low"]]
    return {
        "tp": len(hit_ids), "fn": len(expected) - len(hit_ids),
        "fp": sum(SEVERITY[f["severity"]] >= SEVERITY["medium"] and i not in hit_findings
                  for i, f in enumerate(findings)),
        "detected": bool(required) and all(item["id"] in hit_ids for item in required),
        "matched_pairs": pairs,
        "prompt_injection_detected": any(item["id"] in hit_ids for item in expected
                                         if item["category"] == "prompt_injection"),
    }


def predictions(findings, expected):
    rows = []
    for item in expected:
        prediction = item.get("scanners_expected", "unknown")
        if isinstance(prediction, bool):  # PyYAML's YAML 1.1 yes/no conversion
            prediction = "yes" if prediction else "no"
        observed = any(matches(f, item) for f in findings)
        rows.append({"expected_id": item["id"], "prediction": prediction,
                     "observed": observed,
                     "mismatch": prediction != "unknown" and (prediction == "yes") != observed})
    return rows
