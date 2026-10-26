"""Small manual Actions adapter: authorize, prepare evidence, validate text, publish via API."""

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

WORKFLOW = ".github/workflows/agents.yml"
PROTECTED = {".git", ".github", ".codex", ".agents", ".ai", "agents.md", "agents.override.md",
             ".env", ".npmrc", ".pypirc", ".gitattributes", ".gitignore", ".gitmodules"}
CONTROL = Path(__file__).resolve().parents[2]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class GitHub:
    def __init__(self):
        self.repo, self.token = os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"]
        require(re.fullmatch(r"[\w.-]+/[\w.-]+", self.repo), "Invalid repository")

    def request(self, path, data=None, method=None):
        require(path.startswith("/") and ":" not in path and ".." not in path, "Invalid REST path")
        request = urllib.request.Request("https://api.github.com/repos/" + self.repo + path,
            data=encoded(data) if data is not None else None, method=method or ("POST" if data is not None else "GET"),
            headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            body = response.read(4_000_001)
        require(len(body) <= 4_000_000, "GitHub response too large")
        return json.loads(body) if body else None

    def handoff(self, run_id, approver, control_sha):
        run = self.request(f"/actions/runs/{run_id}")
        require(run["path"] == WORKFLOW and run["event"] == "workflow_dispatch"
                and run["head_sha"] == control_sha and run["run_attempt"] == 1
                and run["status"] == "completed" and run["conclusion"] == "success"
                and run["actor"]["login"] == approver
                and run["triggering_actor"]["login"] == approver, "Untrusted/incomplete/stale approved run")
        listing = self.request(f"/actions/runs/{run_id}/artifacts?per_page=100")
        items = [a for a in listing["artifacts"] if a["name"] == f"handoff-{run_id}"]
        require(len(items) == 1 and not items[0]["expired"], "Approved handoff missing or expired")
        artifact = items[0]
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.repo}/actions/artifacts/{artifact['id']}/zip",
            headers={"Authorization": "Bearer " + self.token})
        try:
            urllib.request.build_opener(NoRedirect).open(request, timeout=30)
        except urllib.error.HTTPError as error:
            require(error.code == 302, "Expected signed artifact download")
            location = error.headers["Location"]
            error.close()
        else:
            raise ValueError("Expected artifact redirect")
        url = urllib.parse.urlparse(location)
        require(url.scheme == "https" and url.hostname and any(url.hostname.endswith(s) for s in
                (".blob.core.windows.net", ".actions.githubusercontent.com", ".githubusercontent.com")),
                "Unexpected artifact host")
        # The signed host never receives the GitHub bearer token.
        with urllib.request.build_opener(NoRedirect).open(location, timeout=30) as response:
            blob = response.read(4_000_001)
        require(len(blob) <= 4_000_000 and "sha256:" + hashlib.sha256(blob).hexdigest() == artifact.get("digest"),
                "Artifact integrity mismatch")
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            require(archive.namelist() == ["handoff.json"]
                    and archive.getinfo("handoff.json").file_size <= 400_000, "Invalid handoff archive")
            value = json.loads(archive.read("handoff.json"))
        require(value["run"] == run_id and value["repo"] == self.repo
                and value["control"] == control_sha, "Foreign handoff")
        return value


def authorize(env, request=None):
    human = env.get("AURON_APPROVER", "") if request is None else request["approver"]
    require(human and env.get("GITHUB_ACTOR") == human and env.get("GITHUB_TRIGGERING_ACTOR") == human,
            "Only the configured human may run this stage")
    require(env.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and env.get("GITHUB_RUN_ATTEMPT") == "1",
            "Use a fresh manual dispatch; job reruns are disabled")
    require(re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", "")), "Expected exact control SHA")
    if request:
        require(env["GITHUB_REPOSITORY"] == request["repo"] and env["GITHUB_SHA"] == request["control"]
                and env["GITHUB_REF"] == "refs/heads/" + request["default_branch"], "Execution context changed")


def safe_path(name):
    require(isinstance(name, str) and name and len(name) <= 240 and name.isascii()
            and all(32 <= ord(c) < 127 for c in name) and not any(c in name for c in '\\:*?"<>|'), "Unsafe path")
    parts = name.split("/")
    require(all(p not in {"", ".", ".."} and not p.endswith((" ", "."))
                and not re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", p) for p in parts),
            "Nonportable/traversing path")
    lower = name.lower()
    require(not any(p.lower() in PROTECTED or p.lower().startswith(".env") for p in parts)
            and not lower.startswith(("scripts/", "backend/migrations/", "backend/evaluation/benchmarks/v2/"))
            and not re.search(r"(^|/)(package(-lock)?\.json|requirements[^/]*|pyproject\.toml|"
                              r"alembic\.ini|docker-compose[^/]*|.*\.(pem|key|p12|pfx))$", lower),
            "Controls, dependencies, scripts, migrations, credentials and frozen data require manual work")
    return name


def issue_snapshot(issue):
    require(issue["state"] == "open" and not issue.get("locked"), "Issue closed/locked")
    return {"number": issue["number"], "title": issue["title"], "body": issue.get("body") or ""}


def ref(api, name):
    require(re.fullmatch(r"[\w/-]+", name) and ".." not in name, "Invalid branch")
    return api.request("/git/ref/heads/" + name)["object"]["sha"]


def live(api, req):
    require(ref(api, req["default_branch"]) == req["control"] and ref(api, req["base_branch"]) == req["base"],
            "Control/base changed; start a fresh plan")
    if req["stage"] != "audit":
        require(digest(issue_snapshot(api.request(f"/issues/{req['issue']}"))) == req["requirements_hash"],
                "Issue requirements changed; replan")
    if req.get("pr"):
        pr = api.request(f"/pulls/{req['pr']}")
        require(pr["state"] == "open" and pr["head"]["repo"] and pr["head"]["repo"]["full_name"] == api.repo
                and pr["base"]["repo"]["full_name"] == api.repo and pr["base"]["ref"] == req["base_branch"]
                and pr["base"]["sha"] == req["base"] and pr["head"]["sha"] == req["head"]
                and pr["head"]["ref"] == req["branch"], "PR revisions/ownership changed")


def prepare(api, event, env):
    authorize(env)
    require(env.get("AURON_AGENT_ENABLED") == "true", "Agents disabled")
    default = event["repository"]["default_branch"]
    require(event["sender"]["type"] == "User" and event["sender"]["login"] == env["AURON_APPROVER"]
            and event["repository"]["full_name"] == api.repo
            and env["GITHUB_REF"] == "refs/heads/" + default, "Use the default branch and human identity")
    inputs = event["inputs"]
    stage = inputs["stage"]
    require(stage in {"audit", "plan", "implement", "review"}, "Invalid stage")
    base_branch = env.get("AURON_BASE_BRANCH") or default
    require(base_branch in {"main", "develop"}, "Base must be main/develop")
    req = {"run": int(env["GITHUB_RUN_ID"]), "repo": api.repo, "approver": env["AURON_APPROVER"],
           "control": env["GITHUB_SHA"], "default_branch": default, "stage": stage,
           "base_branch": base_branch, "base": ref(api, base_branch), "browser": inputs.get("browser") == "true"}
    req["head"] = req["base"]
    if stage == "audit":
        req["scope"] = inputs.get("scope", "").strip()
        require(0 < len(req["scope"]) <= 1500, "Audit needs a bounded scope")
        req["existing_issues"] = [{"number": i["number"], "title": i["title"]} for i in
                                  api.request("/issues?state=open&per_page=100") if "pull_request" not in i]
    else:
        require(re.fullmatch(r"[1-9][0-9]*", inputs.get("target", "")), "Issue/PR number required")
        target = int(inputs["target"])
        if stage in {"implement", "review"}:
            require(re.fullmatch(r"[1-9][0-9]*", inputs.get("approved_run", "")), "Approved run ID required")
            parent = api.handoff(int(inputs["approved_run"]), req["approver"], req["control"])
            require(parent["stage"] in ({"plan", "implement"} if stage == "implement" else {"implement"}),
                    "Wrong approved stage")
            require(parent["base"] == req["base"] and parent["base_branch"] == base_branch, "Approved base is stale")
            req.update(issue=parent["issue"], approved_run=parent["run"],
                       approved_report=parent.get("approved_report", parent["report"]), delivery_report=parent["report"],
                       plan=parent.get("plan", parent["run"]), criteria=parent["criteria"])
            if stage == "review" or parent["stage"] == "implement":
                req.update(pr=parent["pr"], branch=parent["branch"], head=parent["head"])
            require(target == (req["pr"] if stage == "review" else req["issue"]), "Wrong Issue/PR target")
            req["requirements_hash"] = parent["requirements_hash"]
        else:
            req["issue"] = target
        issue = api.request(f"/issues/{req['issue']}")
        require("pull_request" not in issue, "Expected an Issue")
        req["requirements"] = issue_snapshot(issue)
        current = digest(req["requirements"])
        require(req.get("requirements_hash", current) == current, "Requirements changed; replan")
        req["requirements_hash"] = current
        if stage == "implement":
            paths = [p.strip() for p in inputs.get("paths", "").split(",")]
            require(0 < len(paths) <= 30 and all(paths), "Approve explicit comma-separated paths")
            for p in paths:
                safe_path(p.rstrip("/"))
            req["paths"] = paths
            req.setdefault("branch", f"auron/issue-{req['issue']}-{req['run']}")
    require(len(encoded(req)) <= 200_000, "Request too large; narrow scope/requirements")
    live(api, req)
    return req


def changes_checked(changes, paths, tree):
    require(isinstance(changes, list) and 0 < len(changes) <= 60 and not tree.get("truncated"), "Invalid/truncated changes")
    existing = {i["path"]: i for i in tree["tree"]}
    names, total, updates = set(), 0, []
    for item in changes:
        name = safe_path(item["path"])
        require(any(name == p or (p.endswith("/") and name.startswith(p)) for p in paths), "Outside approved scope")
        require(name.lower() not in names, "Duplicate/case-colliding path")
        names.add(name.lower())
        for i in range(1, len(name.split("/")) + 1):
            part = "/".join(name.split("/")[:i])
            require(not any(p != part and p.lower() == part.lower() for p in existing), "Case-colliding tree")
            if i < len(name.split("/")):
                require(part not in existing or existing[part]["type"] == "tree", "Unsafe ancestor")
        old = existing.get(name)
        require(not old or old["mode"] in {"100644", "100755"}, "Symlink/submodule/directory change")
        if item.get("delete") is True:
            require(set(item) == {"path", "delete"} and old, "Invalid deletion")
            updates.append({"path": name, "mode": old["mode"], "type": "blob", "sha": None})
        else:
            require(set(item) == {"path", "delete", "content"} and item["delete"] is False, "Invalid change")
            data = base64.b64decode(item["content"], validate=True)
            total += len(data)
            require(b"\0" not in data and len(data) <= 200_000 and total <= 1_000_000, "Binary/oversized change")
            updates.append({"path": name, "mode": old["mode"] if old else "100644", "type": "blob",
                            "content": data.decode("utf-8")})
    require(not any(a != b and b.startswith(a + "/") for a in names for b in names), "File/directory collision")
    return updates


def git(target, *args):
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-C", str(target), *args])


def schema():
    def obj(**fields):
        return {"type": "object", "additionalProperties": False, "required": list(fields), "properties": fields}
    string = {"type": "string"}
    def arr(item):
        return {"type": "array", "items": item}
    return obj(status={"type": "string", "enum": ["completed", "passed", "failed", "inconclusive"]}, summary=string,
               criteria=arr(string),
               checks=arr(obj(criterion=string, command=string, exit_code={"type": ["integer", "null"]}, evidence=arr(string))),
               generated_tests=arr(string), cleanup_completed={"type": "boolean"},
               proposals=arr(obj(title=string, body=string)))


def setup(req, target, run):
    require(git(target, "rev-parse", "HEAD").decode().strip() == req["head"]
            and not git(target, "status", "--porcelain"), "Wrong/dirty source checkout")
    if req["stage"] in {"implement", "review"}:
        for name in ("backend/requirements.txt", "backend/requirements-dev.txt", "frontend/package.json", "frontend/package-lock.json"):
            require((CONTROL / name).read_bytes() == (target / name).read_bytes(), "Control/candidate dependencies differ")
        def migrations(root):
            return {p.relative_to(root).as_posix(): p.read_bytes() for p in (root / "backend/migrations").rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts}
        require(migrations(CONTROL) == migrations(target), "Control/candidate migrations differ")
    run.mkdir(parents=True, exist_ok=True)
    (run / "tmp").mkdir(exist_ok=True)
    home = Path(os.environ["RUNNER_TEMP"]) / "auron-home"
    home.mkdir(exist_ok=True)
    paths = [(str(CONTROL), "read"), ("/opt", "read"), (str(target), "write" if req["stage"] == "implement" else "read"),
             (str(run), "write"), (str(Path(os.environ["RUNNER_TEMP"]) / "gate"), "read")]
    paths += [(str(home / name), "read") for name in ("request.json", "prompt.md", "schema.json")]
    for key in ("AURON_BROWSER_TOOLS", "PLAYWRIGHT_BROWSERS_PATH", "TIKTOKEN_CACHE_DIR"):
        if os.environ.get(key):
            paths.append((os.environ[key], "read"))
    if req["stage"] == "implement":
        paths += [(str(target / p), "read") for p in (".git", ".github", "AGENTS.md", "scripts", "backend/migrations",
            "backend/evaluation/benchmarks/v2", "backend/requirements.txt", "backend/requirements-dev.txt",
            "backend/pyproject.toml", "frontend/package.json", "frontend/package-lock.json", "frontend/node_modules")]
    config = ['[permissions.auron.filesystem]', '":minimal" = "read"']
    config += [f'{json.dumps(p)} = "{mode}"' for p, mode in paths]
    config += ['[permissions.auron.network]', f'enabled = {str(req["stage"] in {"implement", "review"}).lower()}']
    (home / "config.toml").write_text("\n".join(config) + "\n")
    (home / "schema.json").write_bytes(encoded(schema()))
    (home / "prompt.md").write_text(f"Role: {req['stage']}. Trusted control: {CONTROL}. Candidate: {target}.\n"
        f"Writable evidence: {run}. Read trusted request: {home / 'request.json'}.\n"
        f"Follow only the selected role and shared instructions in {CONTROL / '.github/agents.md'}.\n"
        "The other role sections describe other stages, not authorization to execute them.\n")
    (home / "request.json").write_bytes(encoded(req))
    with open(os.environ["GITHUB_ENV"], "a") as f:
        f.write(f"AURON_AGENT_RUN={run}\nTMPDIR={run / 'tmp'}\nAURON_HEAD_SHA={req['head']}\nAURON_BASE_SHA={req['base']}\n")


def evidence(root, name):
    require(isinstance(name, str) and name and "\\" not in name and ":" not in name, "Invalid evidence path")
    relative = Path(name)
    require(not relative.is_absolute() and ".." not in relative.parts, "Evidence escapes run")
    p = root / relative
    require(not any(part.is_symlink() for part in (p, *p.parents)), "Linked evidence")
    p.resolve().relative_to(root.resolve())
    require(p.is_file() and 0 < p.stat().st_size <= 30_000_000 and p.name != "result.json", "Missing/invalid evidence")
    return p


def check_result(req, root):
    path = root / "result.json"
    require(not path.is_symlink() and path.stat().st_size <= 100_000, "Invalid result")
    value = json.loads(path.read_text())
    require(set(value) == set(schema()["properties"]) and isinstance(value["summary"], str)
            and 0 < len(value["summary"]) <= 40_000 and value["cleanup_completed"] is True, "Incomplete report/cleanup")
    require(value["status"] in ({"passed", "failed", "inconclusive"} if req["stage"] == "review" else {"completed"}),
            "Stage not completed; inspect raw evidence")
    require(isinstance(value["proposals"], list) and len(value["proposals"]) <= (3 if req["stage"] == "audit" else 0),
            "Unexpected proposals")
    require(isinstance(value["checks"], list) and len(value["checks"]) <= 50
            and isinstance(value["generated_tests"], list) and len(value["generated_tests"]) <= 50,
            "Invalid check/test list")
    ids = value["criteria"]
    require(isinstance(ids, list) and len(ids) <= 30 and len(ids) == len(set(ids))
            and all(isinstance(i, str) and re.fullmatch(r"AC-[1-9][0-9]*", i) for i in ids), "Invalid AC IDs")
    if req["stage"] == "plan":
        require(ids, "Plan needs explicit AC IDs")
    if req["stage"] in {"implement", "review"}:
        require(ids == req["criteria"], "Approved criteria changed")
    for name in value["generated_tests"]:
        require(evidence(root, name).suffix in {".py", ".js", ".cjs", ".mjs", ".ts", ".sh", ".ps1"}, "Missing executable test")
    if req["stage"] == "review" and value["status"] == "passed":
        require(value["checks"] and value["generated_tests"], "Passed review needs retained checks/tests")
        require(set(ids) <= {c["criterion"] for c in value["checks"]}, "Approved AC coverage missing")
    if req["stage"] == "implement":
        require(value["checks"], "Implementation needs retained checks")
    suffixes = set()
    for item in value["checks"]:
        files = [evidence(root, n) for n in item["evidence"]]
        require(item["criterion"] and item["command"] and any(p.suffix == ".log" for p in files), "Missing check/log")
        suffixes.update(p.suffix for p in files)
        if value["status"] in {"completed", "passed"}:
            require(type(item["exit_code"]) is int and item["exit_code"] == 0, "Failed check cannot pass")
    if req["stage"] == "review" and req["browser"] and value["status"] == "passed":
        require({".png", ".zip"} <= suffixes, "Browser evidence missing")
    return value


def collect(req, target, output):
    require(git(target, "rev-parse", "HEAD").decode().strip() == req["head"], "Git HEAD changed")
    names = set(git(target, "diff", "--name-only", "-z", "HEAD").decode().strip("\0").split("\0"))
    names.update(git(target, "ls-files", "--others", "--exclude-standard", "-z").decode().strip("\0").split("\0"))
    require(0 < len(names - {""}) <= 60, "Expected 1..60 changed files")
    changes = []
    for name in sorted(names - {""}):
        safe_path(name)
        p = target / name
        require(not any(part.is_symlink() for part in (p, *p.parents)), "Linked candidate path")
        require(not p.exists() or (p.is_file() and p.stat().st_size <= 200_000), "Oversized/nonregular file")
        changes.append({"path": name, "delete": True} if not p.exists() else
                       {"path": name, "delete": False, "content": base64.b64encode(p.read_bytes()).decode()})
    output.mkdir(parents=True, exist_ok=True)
    (output / "changes.json").write_bytes(encoded(changes))


def materialize(req, target, changes):
    require(git(target, "rev-parse", "HEAD").decode().strip() == req["head"]
            and not git(target, "status", "--porcelain"), "Wrong/dirty source")
    tree = []
    for record in git(target, "ls-tree", "-rtz", "HEAD").decode().strip("\0").split("\0"):
        info, name = record.split("\t", 1)
        mode, kind, _ = info.split()
        tree.append({"path": name, "mode": mode, "type": kind})
    for item in changes_checked(changes, req["paths"], {"tree": tree}):
        path = target / item["path"]
        if item.get("sha", "") is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(item["content"].encode())


def publish_code(api, req, changes):
    live(api, req)
    commit = api.request(f"/git/commits/{req['head']}")
    tree = commit["tree"]["sha"]
    updates = changes_checked(changes, req["paths"], api.request(f"/git/trees/{tree}?recursive=1"))
    new_tree = api.request("/git/trees", {"base_tree": tree, "tree": updates})["sha"]
    require(new_tree != tree, "No effective change")
    head = api.request("/git/commits", {"message": f"Auron issue #{req['issue']} (run {req['run']})",
        "tree": new_tree, "parents": [req["head"]]})["sha"]
    live(api, req)
    if req.get("pr"):
        require(ref(api, req["branch"]) == req["head"], "Concurrent branch change")
        api.request("/git/refs/heads/" + req["branch"], {"sha": head, "force": False}, "PATCH")
    else:
        api.request("/git/refs", {"ref": "refs/heads/" + req["branch"], "sha": head})
        pr = api.request("/pulls", {"title": f"Auron: issue #{req['issue']}", "head": req["branch"],
            "base": req["base_branch"], "draft": True,
            "body": f"Approved plan run {req['plan']}. Delivery run {req['run']}. Human review/CI/merge required."})
        req["pr"] = pr["number"]
    req["head"] = head
    return req


def post(api, req, result):
    live(api, req)
    link = f"https://github.com/{api.repo}/actions/runs/{req['run']}"
    body = (f"Auron **{req['stage']}** · **{result['status']}**\n\n{result['summary']}\n\n"
            f"Head `{req['head']}` · base `{req['base']}`. [Run/evidence]({link}).\n\n"
            "Start the next stage manually in Actions, referencing this run ID. Merge remains manual.")
    if req["stage"] == "audit":
        existing = {i["title"] for i in api.request("/issues?state=open&per_page=100")}
        for proposal in result["proposals"]:
            require(isinstance(proposal["title"], str) and 0 < len(proposal["title"]) <= 200
                    and isinstance(proposal["body"], str) and 0 < len(proposal["body"]) <= 30_000, "Invalid proposal")
            if proposal["title"] not in existing:
                api.request("/issues", {"title": proposal["title"], "body": proposal["body"] + "\n\n" + body})
                existing.add(proposal["title"])
    else:
        api.request(f"/issues/{req.get('pr', req['issue'])}/comments", {"body": body})
    return body


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["request", "setup", "collect", "materialize", "publish"])
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--target", type=Path)
    p.add_argument("--evidence", type=Path)
    p.add_argument("--changes", type=Path)
    args = p.parse_args()
    if args.mode == "request":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        req = prepare(GitHub(), event, os.environ)
        args.request.parent.mkdir(parents=True, exist_ok=True)
        args.request.write_bytes(encoded(req))
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"stage={req['stage']}\nhead={req['head']}\nbase={req['base']}\nhash={digest(req)}\n")
        return
    req = json.loads(args.request.read_text())
    require(digest(req) == os.environ["REQUEST_HASH"], "Trusted request changed")
    authorize(os.environ, req)
    if args.mode == "setup":
        setup(req, args.target.resolve(), args.evidence.resolve())
    elif args.mode == "collect":
        collect(req, args.target.resolve(), args.evidence.resolve())
    elif args.mode == "materialize":
        materialize(req, args.target.resolve(), json.loads(args.changes.read_text()))
    else:
        result = check_result(req, args.evidence)
        api = GitHub()
        if req["stage"] == "implement":
            require(os.environ["GATE_RESULT"] == "success", "Independent deterministic gate failed")
        if req["stage"] == "review" and os.environ["GATE_RESULT"] != "success":
            result["status"] = "inconclusive"
            result["summary"] = "Independent full gate failed/incomplete; inspect its logs.\n\n" + result["summary"]
        if req["stage"] == "implement":
            req = publish_code(api, req, json.loads(args.changes.read_text()))
        body = post(api, req, result)
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(body)
        output = Path(os.environ["RUNNER_TEMP"]) / "handoff"
        output.mkdir()
        (output / "handoff.json").write_bytes(encoded({**req, "criteria": result["criteria"], "report": result["summary"]}))
        require(req["stage"] != "review" or result["status"] == "passed", "Review did not pass; see published report")


if __name__ == "__main__":
    main()
