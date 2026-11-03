#!/usr/bin/env python3
"""Deterministic, idempotent GitHub commenter; no model and no execution tools."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

MARKER = "<!-- claude-infra-review:sticky -->"
BOT = "github-actions[bot]"


class GitHub:
    def __init__(self, token, api_url=None):
        self.token = token
        self.api_url = (api_url or os.environ.get("GITHUB_API_URL", "https://api.github.com")).rstrip("/")

    def request(self, method, path, data=None):
        request = Request(self.api_url + path, method=method,
                          data=json.dumps(data).encode() if data is not None else None,
                          headers={"Authorization": "Bearer " + self.token,
                                   "Accept": "application/vnd.github+json",
                                   "X-GitHub-Api-Version": "2022-11-28",
                                   "Content-Type": "application/json"})
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def pages(self, path):
        for page in range(1, 1001):
            values = self.request("GET", path + f"?per_page=100&page={page}")
            if not isinstance(values, list):
                raise ValueError("invalid API pagination")
            yield from values
            if len(values) < 100:
                return
        raise ValueError("pagination limit exceeded")


def post(api, repo, pr, head_sha, body, inline):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not str(pr).isdigit():
        raise ValueError("invalid repository or PR")
    if not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise ValueError("invalid commit")
    if not body.startswith(MARKER) or len(body) > 60_000 or len(inline) > 10:
        raise ValueError("invalid comment payload")
    base = f"/repos/{repo}"
    current = api.request("GET", base + f"/pulls/{pr}")
    if current["head"]["sha"] != head_sha or current["state"] != "open":
        raise ValueError("PR changed or closed; refusing stale review")
    existing = list(api.pages(base + f"/issues/{pr}/comments"))
    sticky = next((c for c in existing if c.get("user", {}).get("login") == BOT and
                   c.get("body", "").startswith(MARKER)), None)
    if sticky:
        api.request("PATCH", base + f"/issues/comments/{int(sticky['id'])}", {"body": body})
    else:
        api.request("POST", base + f"/issues/{pr}/comments", {"body": body})
    markers = set()
    for comment in api.pages(base + f"/pulls/{pr}/comments"):
        if comment.get("user", {}).get("login") == BOT:
            markers.update(re.findall(r"<!-- cir:finding:[0-9a-f]{40} -->", comment.get("body", "")))
    for item in inline:
        if set(item) != {"commit_id", "path", "line", "side", "body"} or item["commit_id"] != head_sha or item["side"] != "RIGHT":
            raise ValueError("invalid inline payload")
        marker = re.match(r"<!-- cir:finding:[0-9a-f]{40} -->", item["body"])
        if not marker:
            raise ValueError("missing inline identity")
        if marker[0] not in markers:
            api.request("POST", base + f"/pulls/{pr}/comments", item)
            markers.add(marker[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--body", type=Path, required=True)
    parser.add_argument("--inline", type=Path, required=True)
    args = parser.parse_args()
    try:
        post(GitHub(os.environ["GH_TOKEN"]), args.repo, args.pr, args.head_sha,
             args.body.read_text(), json.loads(args.inline.read_text()))
    except Exception:
        # HTTP exception bodies can echo model text or credentials; keep logs fixed.
        print("Posting failed; inspect permissions and PR state", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
