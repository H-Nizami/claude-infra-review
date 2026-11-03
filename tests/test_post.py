import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from post_comment import GitHub, MARKER, post

HEAD = "a" * 40
FINDING = "<!-- cir:finding:" + "b" * 40 + " -->"
INLINE = {"commit_id": HEAD, "path": "fixtures/terraform/main.tf", "line": 2,
          "side": "RIGHT", "body": FINDING + "\nAn escaped finding"}


class FakeAPI:
    def __init__(self, comments=None, inline=None, head=HEAD):
        self.comments = comments or []
        self.inline = inline or []
        self.head = head
        self.calls = []

    def request(self, method, path, data=None):
        self.calls.append((method, path, data))
        if method == "GET":
            return {"head": {"sha": self.head}, "state": "open"}
        if path.endswith("/issues/3/comments"):
            self.comments.append({"id": 42, "user": {"login": "github-actions[bot]"}, "body": data["body"]})
        elif path.endswith("/pulls/3/comments"):
            self.inline.append({"id": 43, "user": {"login": "github-actions[bot]"}, "body": data["body"]})
        return {}

    def pages(self, path):
        return iter(self.comments if "/issues/" in path else self.inline)


def test_rerun_updates_sticky_and_deduplicates_inline():
    api = FakeAPI()
    post(api, "owner/repo", 3, HEAD, MARKER + "\nReview", [INLINE])
    post(api, "owner/repo", 3, HEAD, MARKER + "\nUpdated", [INLINE])
    assert len(api.comments) == 1 and len(api.inline) == 1
    assert any(method == "PATCH" and path.endswith("/issues/comments/42") for method, path, _ in api.calls)


def test_only_bot_owned_markers_are_reused():
    api = FakeAPI(comments=[{"id": 9, "user": {"login": "attacker"}, "body": MARKER}],
                  inline=[{"user": {"login": "attacker"}, "body": FINDING}])
    post(api, "owner/repo", 3, HEAD, MARKER + "\nReview", [INLINE])
    assert sum(method == "POST" for method, _, _ in api.calls) == 2


def test_stale_commit_prevents_all_writes():
    api = FakeAPI(head="c" * 40)
    with pytest.raises(ValueError):
        post(api, "owner/repo", 3, HEAD, MARKER, [INLINE])
    assert all(method == "GET" for method, _, _ in api.calls)


def test_pagination_reaches_second_page(monkeypatch):
    api = GitHub("fake-token")
    calls = []
    def request(method, path, data=None):
        calls.append(path)
        return [{"id": i} for i in range(100)] if path.endswith("&page=1") else [{"id": 101}]
    monkeypatch.setattr(api, "request", request)
    assert len(list(api.pages("/repos/o/r/issues/3/comments"))) == 101
    assert len(calls) == 2


def test_urllib_request_contract(monkeypatch):
    captured = []
    class Response:
        def __enter__(self):
            from io import BytesIO
            return BytesIO(b'{"id": 1}')
        def __exit__(self, *args):
            pass
    def opener(request, timeout):
        captured.append(request)
        assert timeout == 30
        return Response()
    monkeypatch.setattr("post_comment.urlopen", opener)
    assert GitHub("fake-token", "https://api.example").request("PATCH", "/repos/o/r/issues/comments/1", {"body": "x"}) == {"id": 1}
    request = captured[0]
    assert request.full_url == "https://api.example/repos/o/r/issues/comments/1"
    assert request.get_method() == "PATCH"
    assert json.loads(request.data) == {"body": "x"}
