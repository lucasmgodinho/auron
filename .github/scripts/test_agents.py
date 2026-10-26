"""Local adapter tests: synthetic GitHub/artifacts, no API, model, browser or DB calls."""

import base64
import copy
import hashlib
import io
import json
import os
import tempfile
import tomllib
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

import agents

A, B, C, D = (char * 40 for char in "abcd")
HUMAN = {"login": "human", "type": "User"}


def env():
    return {"AURON_APPROVER": "human", "AURON_AGENT_ENABLED": "true", "AURON_BASE_BRANCH": "develop",
            "GITHUB_ACTOR": "human", "GITHUB_TRIGGERING_ACTOR": "human", "GITHUB_SHA": A,
            "GITHUB_REPOSITORY": "human/auron", "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main", "GITHUB_RUN_ID": "100", "GITHUB_RUN_ATTEMPT": "1"}


def event(stage="plan", target="7", approved="90", paths="backend/app/example.py"):
    return {"repository": {"default_branch": "main", "full_name": "human/auron"}, "sender": HUMAN,
            "inputs": {"stage": stage, "target": target, "approved_run": approved, "paths": paths,
                       "scope": "Inspect one small area", "browser": "true"}}


class FakeAPI:
    repo = "human/auron"

    def __init__(self):
        self.refs = {"main": A, "develop": B}
        self.issue = {"number": 7, "title": "Observable issue", "body": "Approved requirement", "state": "open"}
        self.parent = {"run": 90, "repo": self.repo, "control": A, "stage": "plan", "base": B,
            "base_branch": "develop", "issue": 7, "report": "Approved plan: AC-1 and path example.py",
            "head": B, "criteria": ["AC-1"], "requirements_hash": agents.digest(agents.issue_snapshot(self.issue))}
        self.pr = {"number": 9, "state": "open", "head": {"sha": C, "ref": "auron/issue-7-90", "repo": {"full_name": self.repo}},
                   "base": {"sha": B, "ref": "develop", "repo": {"full_name": self.repo}}}
        self.tree = {"tree": [{"path": "backend", "type": "tree", "mode": "040000"},
                              {"path": "backend/app", "type": "tree", "mode": "040000"},
                              {"path": "backend/app/example.py", "type": "blob", "mode": "100644"}]}
        self.writes = []

    def handoff(self, *args):
        return copy.deepcopy(self.parent)

    def request(self, path, data=None, method=None):
        if data is not None:
            self.writes.append((path, data, method))
            if path == "/git/trees":
                return {"sha": D}
            if path == "/git/commits":
                return {"sha": C}
            if path == "/pulls":
                self.pr["head"].update(sha=C, ref=data["head"])
                return self.pr
            if path == "/git/refs":
                self.refs[data["ref"].removeprefix("refs/heads/")] = data["sha"]
            if path.startswith("/git/refs/heads/"):
                self.refs[path.removeprefix("/git/refs/heads/")] = data["sha"]
                self.pr["head"]["sha"] = data["sha"]
            return {}
        if path.startswith("/git/ref/heads/"):
            return {"object": {"sha": self.refs[path.removeprefix("/git/ref/heads/")]}}
        if path == "/issues/7":
            return self.issue
        if path == "/pulls/9":
            return self.pr
        if path.startswith("/issues?"):
            return [self.issue]
        if path.startswith("/git/commits/"):
            return {"tree": {"sha": B}}
        if path.startswith("/git/trees/"):
            return self.tree
        raise AssertionError(path)


def change(name="backend/app/example.py", content=b"print('literal $()')\n"):
    return {"path": name, "delete": False, "content": base64.b64encode(content).decode()}


class AdapterTests(unittest.TestCase):
    def test_actor_rerun_event_and_exact_revision_guards(self):
        for key, bad in [("GITHUB_ACTOR", "outsider"), ("GITHUB_TRIGGERING_ACTOR", "outsider"),
                         ("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_EVENT_NAME", "issue_comment"),
                         ("GITHUB_SHA", "main"), ("AURON_APPROVER", "")]:
            value = env()
            value[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                agents.authorize(value)

    def test_fresh_plan_uses_real_issue_and_live_base(self):
        req = agents.prepare(FakeAPI(), event(), env())
        self.assertEqual((req["stage"], req["issue"], req["head"]), ("plan", 7, B))

    def test_disabled_bot_wrong_repo_ref_or_target_cannot_request(self):
        for field, value in [("sender", {"login": "human", "type": "Bot"}),
                             ("repository", {"default_branch": "other", "full_name": "human/auron"})]:
            data = event()
            data[field] = value
            with self.assertRaises(ValueError):
                agents.prepare(FakeAPI(), data, env())
        for key, value in [("AURON_AGENT_ENABLED", "false"), ("GITHUB_REF", "refs/heads/develop")]:
            variables = env()
            variables[key] = value
            with self.assertRaises(ValueError):
                agents.prepare(FakeAPI(), event(), variables)
        with self.assertRaises(ValueError):
            agents.prepare(FakeAPI(), event(target="7; arbitrary"), env())

    def test_implementation_requires_right_approved_plan_and_scope(self):
        api = FakeAPI()
        req = agents.prepare(api, event("implement"), env())
        self.assertEqual(req["plan"], 90)
        self.assertEqual(req["paths"], ["backend/app/example.py"])
        for value in ("", "main", "90-1"):
            with self.assertRaises(ValueError):
                agents.prepare(api, event("implement", approved=value), env())
        api.parent["stage"] = "audit"
        with self.assertRaises(ValueError):
            agents.prepare(api, event("implement"), env())

    def test_stale_issue_base_and_wrong_target_are_refused(self):
        for mutate in (lambda a: a.issue.update(body="Changed requirement"),
                       lambda a: a.refs.update(develop=C), lambda a: a.parent.update(issue=8)):
            api = FakeAPI()
            mutate(api)
            with self.assertRaises(ValueError):
                agents.prepare(api, event("implement"), env())

    def test_review_and_correction_bind_original_plan_and_delivery(self):
        api = FakeAPI()
        api.parent.update(stage="implement", plan=80, head=C, pr=9, branch="auron/issue-7-90",
                          approved_report="Original approved ACs", report="Delivery report")
        api.refs["auron/issue-7-90"] = C
        for stage, target in (("review", "9"), ("implement", "7")):
            req = agents.prepare(api, event(stage, target), env())
            self.assertEqual(req["approved_report"], "Original approved ACs")
            self.assertEqual(req["head"], C)
            self.assertEqual(req["plan"], 80)
        api.pr["head"]["sha"] = D
        with self.assertRaises(ValueError):
            agents.prepare(api, event("review", "9"), env())

    def test_before_publication_rechecks_issue_and_controls(self):
        for mutate in (lambda a: a.issue.update(state="closed"), lambda a: a.issue.update(body="changed"),
                       lambda a: a.refs.update(main=D), lambda a: a.refs.update(develop=D)):
            api = FakeAPI()
            req = agents.prepare(api, event(), env())
            mutate(api)
            with self.assertRaises(ValueError):
                agents.live(api, req)

    def test_path_guards_cover_controls_secrets_dependencies_and_windows(self):
        names = ["../x", "/x", "C:/x", "backend\\x", "backend/AGENTS.md", "AGENTS.override.md",
                 ".git/config", ".github/agents.md", "scripts/verify.ps1", "backend/migrations/x.py",
                 "backend/.env.test", "frontend/package.json", "backend/app/NUL.txt", "backend/app/x?.py",
                 "backend/app/x.", "backend/app/x|.py", "backend/app/é.py", "backend/requirements-dev.txt",
                 "backend/evaluation/benchmarks/v2/x", ".ai/x", ".agents/x", ".codex/x"]
        for name in names:
            with self.subTest(name=name), self.assertRaises(ValueError):
                agents.safe_path(name)

    def test_text_change_contract_and_out_of_scope_binary_duplicate_rejection(self):
        api = FakeAPI()
        self.assertEqual(agents.changes_checked([change()], ["backend/app/"], api.tree)[0]["mode"], "100644")
        cases = [([change()], ["backend/other.py"]), ([change(content=b"\0")], ["backend/app/"]),
                 ([change(), change()], ["backend/app/"]), ([change(content=b"x" * 200001)], ["backend/app/"]),
                 ([{**change(), "mode": "120000"}], ["backend/app/"])]
        for changes, paths in cases:
            with self.assertRaises(ValueError):
                agents.changes_checked(changes, paths, api.tree)

    def test_symlink_submodule_parent_and_case_collision_refused(self):
        for name, mode, kind in (("backend/app/example.py", "120000", "blob"),
                                 ("backend/app/example.py", "160000", "commit"), ("backend/app", "120000", "blob")):
            tree = FakeAPI().tree
            next(i for i in tree["tree"] if i["path"] == name).update(mode=mode, type=kind)
            with self.assertRaises(ValueError):
                agents.changes_checked([change()], ["backend/app/"], tree)
        tree = FakeAPI().tree
        tree["tree"][0]["path"] = "Backend"
        with self.assertRaises(ValueError):
            agents.changes_checked([change()], ["backend/app/"], tree)

    def test_publisher_uses_only_api_and_draft_pr_without_force(self):
        api = FakeAPI()
        req = agents.prepare(api, event("implement"), env())
        result = agents.publish_code(api, req, [change()])
        self.assertEqual((result["pr"], result["head"]), (9, C))
        self.assertTrue(next(data for path, data, _ in api.writes if path == "/pulls")["draft"])
        self.assertFalse(any(data.get("force") for _, data, _ in api.writes))

    def test_audit_deduplicates_identical_proposals(self):
        api = FakeAPI()
        req = agents.prepare(api, event("audit"), env())
        result = {"status": "completed", "summary": "Audit", "proposals": [{"title": "New", "body": "Hypothesis"}] * 2}
        agents.post(api, req, result)
        self.assertEqual(sum(path == "/issues" for path, _, _ in api.writes), 1)

    def test_manual_publisher_rerun_is_denied_with_existing_authorization(self):
        req = agents.prepare(FakeAPI(), event(), env())
        for key, value in (("GITHUB_TRIGGERING_ACTOR", "other"), ("GITHUB_REPOSITORY", "other/repo"),
                           ("GITHUB_SHA", D), ("GITHUB_RUN_ATTEMPT", "2")):
            variables = env()
            variables[key] = value
            with self.assertRaises(ValueError):
                agents.authorize(variables, req)


class EvidenceTests(unittest.TestCase):
    def test_each_role_generates_parseable_profile_with_expected_write_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            control, target = root / "control", root / "candidate"
            for base in (control, target):
                for name in ("backend/requirements.txt", "backend/requirements-dev.txt", "frontend/package.json",
                             "frontend/package-lock.json", "backend/migrations/example.py"):
                    path = base / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("trusted dependency/migration fixture")
            def read_git(_target, *args):
                return B.encode() if args == ("rev-parse", "HEAD") else b""
            variables = {"RUNNER_TEMP": str(root), "GITHUB_ENV": str(root / "env")}
            with patch.object(agents, "CONTROL", control), patch.object(agents, "git", side_effect=read_git), patch.dict(os.environ, variables):
                for stage in ("audit", "plan", "implement", "review"):
                    req = {"stage": stage, "head": B, "base": B}
                    run = root / "evidence" / stage
                    agents.setup(req, target, run)
                    home = root / "auron-home"
                    profile = tomllib.loads((home / "config.toml").read_text())["permissions"]["auron"]
                    self.assertEqual(profile["filesystem"][str(target)], "write" if stage == "implement" else "read")
                    self.assertEqual(profile["filesystem"][str(control)], "read")
                    self.assertEqual(profile["filesystem"][str(run)], "write")
                    self.assertEqual(profile["network"]["enabled"], stage in {"implement", "review"})
                    self.assertEqual(json.loads((home / "request.json").read_text()), req)
                    self.assertIn(f"Role: {stage}.", (home / "prompt.md").read_text())
                    if stage == "implement":
                        self.assertEqual(profile["filesystem"][str(target / ".github")], "read")
                        self.assertEqual(profile["filesystem"][str(target / "scripts")], "read")
                (target / "backend/requirements.txt").write_text("unapproved dependency")
                with self.assertRaisesRegex(ValueError, "dependencies differ"):
                    agents.setup({"stage": "review", "head": B}, target, root / "rejected")

    def test_pass_needs_executed_tests_logs_cleanup_and_optional_browser(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("test.py", "test.log", "screen.png", "trace.zip"):
                (root / name).write_text("Synthetic structural fixture, not browser proof")
            req = {"stage": "review", "browser": True, "criteria": ["AC-1"]}
            value = {"status": "passed", "summary": "Assertions", "cleanup_completed": True, "proposals": [], "criteria": ["AC-1"],
                     "generated_tests": ["test.py"], "checks": [{"criterion": "AC-1", "command": "synthetic",
                         "exit_code": 0, "evidence": ["test.log", "screen.png", "trace.zip"]}]}
            for mutate in (lambda v: v.update(cleanup_completed=False), lambda v: v.update(checks=[]),
                           lambda v: v.update(generated_tests=[]), lambda v: v["checks"][0].update(exit_code=1),
                           lambda v: v["checks"][0].update(evidence=["test.log"]),
                           lambda v: v["checks"][0].update(evidence=["../test.log"]),
                           lambda v: v.update(criteria=["AC-2"]),
                           lambda v: v["checks"][0].update(criterion="AC-2")):
                data = copy.deepcopy(value)
                mutate(data)
                (root / "result.json").write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    agents.check_result(req, root)
            (root / "result.json").write_text(json.dumps(value))
            self.assertEqual(agents.check_result(req, root)["status"], "passed")

    def test_workflow_pays_only_after_trusted_setup_and_separates_write_tokens(self):
        import re
        workflow = (agents.CONTROL / ".github/workflows/agents.yml").read_text()
        matches = list(re.finditer(r"^  ([a-z][a-z-]+):$", workflow, re.MULTILINE))
        jobs = {m[1]: workflow[m.start():matches[i + 1].start() if i + 1 < len(matches) else len(workflow)]
                for i, m in enumerate(matches)}
        self.assertEqual({n for n, body in jobs.items() if "secrets.OPENAI_API_KEY_GL" in body}, {"agent"})
        before = jobs["agent"].split("uses: openai/codex-action", 1)[0]
        self.assertNotIn("cache:", before)
        self.assertIsNone(re.search(r"working-directory: candidate|\(cd candidate|npm --prefix candidate|python candidate/", before))
        for name in ("publish-code", "publish-report", "fast", "full"):
            self.assertNotIn("secrets.", jobs[name])
        for name in ("publish-code", "publish-report"):
            self.assertNotIn("candidate/", jobs[name])


class HandoffTests(unittest.TestCase):
    def test_origin_and_download_digest_and_no_token_forwarding(self):
        value = {"run": 90, "repo": "human/auron", "control": A}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("handoff.json", json.dumps(value))
        blob = stream.getvalue()
        run = {"path": agents.WORKFLOW, "event": "workflow_dispatch", "head_sha": A,
               "run_attempt": 1, "status": "completed", "conclusion": "success",
               "actor": HUMAN, "triggering_actor": HUMAN}
        listing = {"artifacts": [{"id": 88, "name": "handoff-90", "expired": False,
                                 "digest": "sha256:" + hashlib.sha256(blob).hexdigest()}]}
        class Transport:
            def __init__(self):
                self.requests = []
            def open(self, request, timeout):
                self.requests.append(request)
                if isinstance(request, str):
                    return io.BytesIO(blob)
                raise urllib.error.HTTPError(request.full_url, 302, "Found",
                    {"Location": "https://test.blob.core.windows.net/signed"}, None)
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "human/auron", "GH_TOKEN": "synthetic"}):
            api = agents.GitHub()
            transport = Transport()
            with patch.object(api, "request", side_effect=[run, listing]), patch("urllib.request.build_opener", return_value=transport):
                self.assertEqual(api.handoff(90, "human", A), value)
            self.assertEqual(transport.requests[0].headers["Authorization"], "Bearer synthetic")
            self.assertIsInstance(transport.requests[1], str)
            for field, invalid in (("path", "other.yml"), ("event", "push"), ("head_sha", D),
                                   ("run_attempt", 2), ("conclusion", "failure")):
                bad = {**run, field: invalid}
                with self.subTest(field=field), patch.object(api, "request", return_value=bad), self.assertRaises(ValueError):
                    api.handoff(90, "human", A)
            bad_listing = copy.deepcopy(listing)
            bad_listing["artifacts"][0]["expired"] = True
            with patch.object(api, "request", side_effect=[run, bad_listing]), self.assertRaises(ValueError):
                api.handoff(90, "human", A)


if __name__ == "__main__":
    unittest.main()
