"""Exercise tool boundaries and shell bypasses without invoking any commands."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude/hooks/guard.py"
spec = importlib.util.spec_from_file_location("guard", HOOK)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

BLOCK = [
    "git push origin main", "git commit -am x", "git tag v1", "git reset --hard", "git rebase main",
    "git merge feature", "git cherry-pick abc", "git am patch", "git apply patch", "git remote add x y",
    "git config core.sshCommand evil", "git -c core.pager=evil log", "git diff --ext-diff",
    "git show --textconv HEAD", "git diff --output=outside", "gh pr merge 3", "gh pr review 3 --approve",
    "gh pr comment 3", "gh pr close 3", "gh issue list", "gh release create v1", "gh secret list",
    "gh variable set X", "gh workflow run x", "gh repo view", "gh api repos/x/y -X POST",
    "gh api repos/x/y --method=DELETE", "gh api repos/x/y -XPOST", "gh api repos/x/y -f x=y",
    "gh api repos/x/y -Fx=y", "gh api repos/x/y --raw-field=x=y", "gh api repos/x/y --input=x",
    "curl example.com", "wget example.com", "http example.com", "nc host 80", "ncat host 80",
    "socat x y", "ssh host", "scp x y", "rsync x y", "ftp host", "telnet host",
    "terraform apply", "tofu destroy", "terraform import x y", "tofu taint x", "tofu untaint x",
    "terraform state push x", "tofu state rm x", "terraform state mv x y", "tofu force-unlock x",
    "terraform plan -out=foo", "terraform fmt", "kubectl apply -f x", "kubectl create namespace x",
    "kubectl delete pod x", "kubectl patch pod x", "kubectl edit pod x", "kubectl replace -f x",
    "kubectl scale deploy x", "kubectl rollout restart deploy x", "kubectl annotate x", "kubectl label x",
    "kubectl exec pod -- sh", "kubectl cp x y", "kubectl port-forward x", "kubectl drain node",
    "kubectl cordon node", "kubectl taint node x", "helm install x", "helm upgrade x", "helm uninstall x",
    "helm rollback x", "helm delete x", "aws ec2 terminate-instances", "aws s3 cp x y",
    "aws ec2 describe-instances --endpoint-url=https://evil.example", "rm -rf x", "dd if=x of=y",
    "mkfs /dev/x", "chmod -R 777 x", "chown -R x y", "echo hi > outside", "echo hi >> docs/x",
    "echo hi | tee outside", "eval 'git push'", "bash -c 'git push'", "sh -c 'git push'",
    "python -c 'evil()'", "node -e 'evil()'", "env FOO=bar git push", "env PATH=evil git diff",
    "/usr/bin/git push", "cat $(git push)", "cat `git push`", "git diff; curl example.com",
    "git diff && git push", "git diff || git commit", "git diff | sh", "git 'unterminated",
    "find . -exec sh x", "rg --pre=evil text", "unknown-reader x", "git diff\ngit push",
]
ALLOW = ["terraform plan", "terraform validate", "terraform fmt -check", "tofu plan", "tofu version",
         "kubectl get pods", "kubectl describe pod x", "kubectl logs x", "git diff", "git status",
         "git show HEAD", "git log --oneline", "gh pr view 3", "gh pr diff 3", "gh api repos/x/y",
         "gh api repos/x/y -X GET", "gh api repos/x/y --method=GET", "aws sts get-caller-identity",
         "aws ec2 describe-instances", "helm list", "cat docs/pins.md", "rg risk fixtures",
         "git diff && git status", "env FOO=bar git diff"]


@pytest.mark.parametrize("command", BLOCK)
def test_blocks(command):
    assert guard.decide({"tool_name": "Bash", "tool_input": {"command": command}}, {})


@pytest.mark.parametrize("command", ALLOW)
def test_allows_local_reads(command):
    assert guard.decide({"tool_name": "Bash", "tool_input": {"command": command}}, {}) is None


@pytest.mark.parametrize("name", ["Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent", "mcp__github__create_comment", "Unknown"])
def test_non_read_tools_blocked(name):
    assert guard.decide({"tool_name": name, "tool_input": {"file_path": "docs/x"}}, {})


def test_internal_structured_output_is_data_only():
    payload = {"summary": "No findings", "risk_level": "none", "findings": [],
               "dropped_scanner_findings": []}
    assert guard.decide({"tool_name": "StructuredOutput", "tool_input": payload}, {}) is None
    assert guard.decide({"tool_name": "StructuredOutput", "tool_input": None}, {})


@pytest.mark.parametrize("path", ["/proc/self/environ", "/etc/passwd", "../secret", ".git/config", ".env.production", ".claude-pr/settings.json", "~/.claude/.credentials.json", "$HOME/.claude/.credentials.json"])
def test_no_sensitive_reads(tmp_path, path):
    assert guard.decide({"tool_name": "Read", "tool_input": {"file_path": path}}, {"CLAUDE_PROJECT_DIR": str(tmp_path)})


def test_docs_write_opt_in_and_symlinks(tmp_path):
    (tmp_path / "docs").mkdir()
    env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
    def check(path):
        return guard.decide({"tool_name": "Write", "tool_input": {"file_path": path}}, env)
    assert check("docs/x")
    env["CIR_ALLOW_DOCS_WRITES"] = "1"
    assert check("docs/x") is None
    assert check("docs/../x")
    (tmp_path / "docs/link").symlink_to(tmp_path.parent, target_is_directory=True)
    assert check("docs/link/x")
    (tmp_path / "readlink").symlink_to("/proc")
    assert guard.decide({"tool_name": "Read", "tool_input": {"file_path": "readlink/self/environ"}}, env)


def test_ci_bash_disabled():
    assert guard.decide({"tool_name": "Bash", "tool_input": {"command": "git diff"}}, {"CI": "true"})


@pytest.mark.parametrize("args", ["-fls /tmp/out", "-fprint0 /tmp/out", "-ok sh x", "-okdir sh x"])
def test_find_exec_write_variants(args):
    assert guard.decide({"tool_name": "Bash", "tool_input": {"command": "find . " + args}}, {})


def test_recursive_reads_are_scoped_and_cannot_search_credentials(tmp_path):
    env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
    assert guard.decide({"tool_name": "Grep", "tool_input": {"path": ".", "glob": ".env"}}, env)
    assert guard.decide({"tool_name": "Grep", "tool_input": {"path": "fixtures", "glob": ".env*"}}, env)
    assert guard.decide({"tool_name": "Grep", "tool_input": {"path": "fixtures", "pattern": "risk"}}, env) is None
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures/link").symlink_to("/proc", target_is_directory=True)
    assert guard.decide({"tool_name": "Grep", "tool_input": {"path": "fixtures", "pattern": "risk"}}, env)


@pytest.mark.parametrize("payload", [None, [], {}, {"tool_name": "Read"}, {"tool_name": "Read", "tool_input": {}}])
def test_malformed_fails_closed(payload):
    assert guard.decide(payload, {})


@pytest.mark.parametrize("name,pattern", [("Glob", "/proc/**"), ("Glob", "../*"), ("Grep", "../../*")])
def test_read_glob_escape(name, pattern):
    key = "pattern" if name == "Glob" else "glob"
    assert guard.decide({"tool_name": name, "tool_input": {key: pattern}}, {})


def test_hook_exit_contract():
    for raw, expected in [("not json", 2), (json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}), 2),
                          (json.dumps({"tool_name": "Read", "tool_input": {"file_path": "README.md"}}), 0)]:
        result = subprocess.run([sys.executable, str(HOOK)], input=raw, text=True, capture_output=True, cwd=ROOT)
        assert result.returncode == expected
        assert "git push" not in result.stderr
