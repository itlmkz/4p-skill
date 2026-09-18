#!/usr/bin/env python3
"""4pp - spawn a 4-pane advisory panel of pi agents in the current Herdr tab.

Panels (roles):
  contraire  - AMO: assistant contraire, critical eye / constructive contradiction
  tester     - empirical verification (runs things, reports observed output)
  reviewer   - code + convention review on the diff
  bigpicture - strategic coherence, drift, scope, one-way doors

Idempotent: panes are labeled `4pp:<role>`. Re-running reuses the panel,
reconciles drifted labels, and only fills in what is missing. --rebrief re-sends
the role briefs.

Advisory posture: panel agents start with `--exclude-tools edit,write` and are
briefed that the coordinator pane is the only writer. They keep bash for reading,
running tests, and git inspection, so the rule is a contract rather than a kernel
boundary; for a hard guarantee run each pane in its own git worktree.

Usage:
  4pp.py [--rebrief] [--json] [-- task words ...]

Env: HERDR_ENV must be 1 (i.e. run inside a Herdr pane).
Optional: 4PP_MODEL, 4PP_THINKING (passed through to pi), 4PP_KIND (default pi),
          4PP_STRICT_NO_WRITE=1 (panes get read/grep/find/ls only: no bash at all,
          the enforced version of the write rule, at the cost of running tests),
          4PP_COORDINATOR_GRANTS_WRITE=1 (coordinator-only: drop the no-write
          posture for a task it has explicitly approved; a panel pane is refused),
          4PP_TASK (alternative to positional task words).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from string import Template

LABEL_PREFIX = "4pp:"
REPORT_DIR = "/tmp/4pp"
START_TIMEOUT_MS = 90000
PROMPT_TIMEOUT_MS = 240000

BRIEF_VERSION = "4p/brief@1"

# The panes speak a versioned contract in both directions: this brief in, and one
# 4p/report@1 json block out. The contract text is derived from the schema at
# runtime, so a brief can never describe a shape the validator will reject.
BRIEF_HEAD = Template("""\
$BRIEF_VERSION  role=$ROLE_KEY  seat=$ROLE_LABEL  name=$ROLE_NAME

[SESSION]
cwd=$CWD
tab=$TAB_ID
pane=$PANE_ID
coordinator_pane=$CALLER_PANE
peers=$PEERS
posture=$TOOL_POSTURE

[OUTPUT]
Your whole answer is one fenced json block.
Write no prose before it. Write no prose after it.
The block must satisfy the contract below.
The coordinator reads it with report.py --extract, so any text outside the block is lost.
$REPORT_RULE

[CONTRACT]
$CONTRACT

[SELF-CHECK]
Before you answer, validate the exact json that you intend to emit.
Put that json in the heredoc. The command must print "valid".
  python3 $VALIDATOR --validate - <<'JSON'
  <your json>
  JSON
Fix each problem it reports. Then answer.
""")

BRIEF_TAIL = Template("""\

[RULES]
1. Stand by until you get a task.
2. The coordinator pane is the only writer. Never change repo files or git state on your own initiative.
3. You are an advisor. Never fix the code, even when the fix is one line.
4. Carry evidence for each finding: kind=file with file and line, or kind=command with command and observed.
5. When you cannot verify something, use verdict=could_not_verify and fill could_not_verify. Never guess.
6. Never merge, push, commit, revert, stash, or delete. Never run a destructive command.
7. Write terse English. Free text is Simplified Technical English: one sentence, 20 words maximum, active voice, no em dash. Drop filler, hedging, and articles where the meaning stays clear. State each fact once. Chinese, Japanese, and Korean get a 45-character budget instead. The validator enforces the length and the em dash.
8. Never drop not, never, no, only, or except. Keep numbers, units, paths, and error strings exact. Ambiguity costs more than the tokens it saves.
9. Do not manufacture objections. Report an empty findings list when the work is sound.
""")


def load_contract() -> tuple[str, str]:
    """Return (contract text, absolute path to the validator).

    Derived from report.schema.json, which is the single source of truth.
    If it cannot be read, the brief says so instead of guessing a shape.
    """
    panel_dir = os.path.dirname(os.path.abspath(__file__))
    validator = os.path.join(panel_dir, "report.py")
    try:
        if panel_dir not in sys.path:
            sys.path.insert(0, panel_dir)
        from report import describe, load_schema

        return describe(load_schema()), validator
    except Exception as exc:  # pragma: no cover - misinstalled package
        return (
            f"contract unavailable ({exc}). Emit a 4p/report@1 json block and validate it with {validator}.",
            validator,
        )

ROLE_BRIEFS = {
    "contraire": Template("""\
Your role: AMO. Regard critique et contradiction constructive on build decisions.
Push back on the decision. Never push back on the person.

Do this:
- State the load-bearing assumption in assumptions[], with its if_false.
- Name the failure mode that nobody has mentioned, and how it would appear in production.
- Give the cheapest test that would disprove the plan, in confirm_test.
- Steelman the rejected path in a finding: what it buys that this one does not.
- Put each decision that belongs to the owner in questions[], with a recommendation. Never leave a decision bare.

Block only on real risk: data loss, security, a broken deploy, an irreversible choice, a silent behavior change. Never block on taste. When the decision is sound, set verdict=ship, leave findings[] empty, and stop.
"""),
    "tester": Template("""\
Your role: tester. You verify empirically. Nothing is true because it reads well.

Do this:
- Run the thing: the build, the typecheck, the tests, the scripts, the deployed url. Put the exact command in evidence.command and what you saw in evidence.observed.
- Map the outcome to verdict: verified gives ship, broken gives block, not run gives could_not_verify.
- Try to break it: empty input, huge input, wrong types, missing env, a re-run after failure, concurrent use.
- Put each thing that you could not run in could_not_verify, with the precise blocker. Name the missing secret, network, runtime, or file.
- Keep the smallest reproduction that isolates the failure.

Never claim a result that you did not observe. Never fix the code. Proving the bug is your job.
"""),
    "reviewer": Template("""\
Your role: reviewer. You review the change against this repo's own standards.

Cover in this order. Cite file and line for each finding:
1. Correctness and behavior change. Does it do what was asked, and does it silently change something else?
2. Edge cases, error handling, failure paths, and what the user sees when it breaks.
3. Security: secrets, injection, authz, data exposure, trust boundaries.
4. Repo conventions: AGENTS.md, file layout, naming, design-system rules.
5. Tests: what is covered, what is asserted weakly, what is missing.
6. Readability and dead code.

Read the real diff. Never trust a summary of it. Do not restate the diff. Report only what you would change and why. Rank each finding blocking, should-fix, or nit.
"""),
    "bigpicture": Template("""\
Your role: big picture. You protect coherence between this change, the product, and the platform.

Ask and answer. Ground each claim in a repo file:
- Which product decision or note does this serve? Does it contradict one? Check AGENTS.md, DESIGN.md, PRODUCT.md, and any decisions directory.
- Does it fork the platform, for example with a second source of truth or a parallel pattern?
- Is it a one-way door? What does undoing it cost in a month?
- Is there a smaller step that gets most of the value now?
- What should be cut? What breaks later: maintenance, migration debt, docs drift, ops load?
- Who is this for, and does the change respect the audience and access boundaries?

Put each decision that belongs to the owner in questions[], with a recommendation. Lead with the single most important coherence risk. When the change is coherent, set verdict=ship, leave findings[] empty, and stop.
"""),
}

ROLE_ORDER = ["contraire", "tester", "reviewer", "bigpicture"]
ROLE_NAMES = {
    "contraire": "AMO (assistant contraire)",
    "tester": "tester",
    "reviewer": "reviewer",
    "bigpicture": "big picture",
}
AGENT_BASES = {
    "contraire": "assistant-contraire",
    "tester": "tester",
    "reviewer": "reviewer",
    "bigpicture": "big-picture",
}


def die(msg: str, code: int = 1) -> None:
    print(f"4pp: {msg}", file=sys.stderr)
    sys.exit(code)


def herdr(*args: str, check: bool = True) -> dict:
    exe = shutil.which("herdr")
    if not exe:
        die("herdr not found in PATH")
    proc = subprocess.run([exe, *args], capture_output=True, text=True)
    out = proc.stdout.strip()
    try:
        payload = json.loads(out) if out else {}
    except json.JSONDecodeError:
        payload = {"raw": out}
    if check and proc.returncode != 0:
        err = payload.get("error") or payload.get("raw") or proc.stderr.strip()
        die(f"herdr {' '.join(args)} failed: {err}")
    payload["_returncode"] = proc.returncode
    return payload


def result_of(payload: dict) -> dict:
    return payload.get("result", payload)


def panes_in_tab(tab_id: str) -> list[dict]:
    workspace = tab_id.split(":")[0]
    payload = result_of(herdr("pane", "list", "--workspace", workspace))
    panes = [p for p in payload.get("panes", []) if p.get("tab_id") == tab_id]
    if not panes:
        return panes
    # pane list omits geometry; take it from the layout so reading order is stable
    anchor = panes[0]["pane_id"]
    layout = result_of(herdr("pane", "layout", "--pane", anchor, check=False)).get("layout", {})
    rects = {p["pane_id"]: p.get("rect", {}) for p in layout.get("panes", [])}
    for pane in panes:
        pane.setdefault("rect", rects.get(pane["pane_id"], {}))
    return panes


def live_agents() -> list[dict]:
    return result_of(herdr("agent", "list")).get("agents", [])


def pane_label(pane: dict) -> str:
    return pane.get("label") or ""


def has_agent(pane: dict) -> bool:
    return bool(pane.get("agent"))


def reading_order(panes: list[dict]) -> list[dict]:
    def key(p: dict) -> tuple[int, int]:
        rect = p.get("rect") or {}
        return (rect.get("y", 0), rect.get("x", 0))

    return sorted(panes, key=key)


def is_panel_agent_name(role: str, name: str) -> bool:
    """True when a live agent name looks like this panel's agent for that role.
    Used only to decide whether a labeled pane may be adopted, never to rename."""
    base = AGENT_BASES[role]
    if name == base:
        return True
    return name.startswith(base + "-") and name[len(base) + 1:].isdigit()


def split(pane_id: str, direction: str, ratio: float) -> str:
    payload = result_of(
        herdr(
            "pane",
            "split",
            pane_id,
            "--direction",
            direction,
            "--ratio",
            str(ratio),
            "--cwd",
            os.getcwd(),
            "--no-focus",
        )
    )
    return payload["pane"]["pane_id"]


def free_agent_name(base: str, taken: set[str]) -> str:
    candidate = base[:32]
    if candidate not in taken:
        taken.add(candidate)
        return candidate
    for n in range(2, 40):
        suffix = f"-{n}"
        candidate = base[: 32 - len(suffix)] + suffix
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    die(f"no free agent name left for {base}")


def brief_for(role: str, ctx: dict) -> str:
    head = BRIEF_HEAD.substitute(
        **ctx,
        ROLE_KEY=role,
        ROLE_LABEL=f"{LABEL_PREFIX}{role}",
        ROLE_NAME=ROLE_NAMES[role],
    )
    body = ROLE_BRIEFS[role].substitute(**ctx)
    return head + "\n[ROLE]\n" + body + BRIEF_TAIL.substitute(**ctx)


def parse_args(argv: list[str]) -> tuple[bool, bool, str]:
    """Return (rebrief, as_json, task). Unknown flags are an error, never silently dropped."""
    known = {"--rebrief": "rebrief", "--json": "json", "--help": "help", "-h": "help"}
    flags: dict[str, bool] = {}
    task_words: list[str] = []
    rest = False
    for arg in argv:
        if rest:
            task_words.append(arg)
        elif arg == "--":
            rest = True
        elif arg in known:
            flags[known[arg]] = True
        elif arg == "-":
            task_words.append(arg)  # bare dash is stdin convention, not a flag
        elif arg.startswith("-"):
            die(f"unknown flag '{arg}'. Known: {', '.join(sorted(known))}. Use -- before task text starting with a dash.")
        else:
            task_words.append(arg)
    if flags.get("help"):
        print(__doc__)
        sys.exit(0)
    return bool(flags.get("rebrief")), bool(flags.get("json")), " ".join(task_words).strip()


def load_state(state_path: str, max_age_s: int = 24 * 3600) -> dict:
    try:
        with open(state_path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    written_at = data.get("written_at")
    if isinstance(written_at, (int, float)) and (time.time() - written_at) > max_age_s:
        return {}  # stale record from an earlier session in this tab slot
    return data


def save_state(state_path: str, tab_id: str, panel: dict, posture: str = "") -> None:
    roles = {
        role: {"pane_id": entry["pane_id"], "agent": entry.get("agent", "")}
        for role, entry in panel.items()
        if not entry["status"].startswith("FAILED") and not entry["status"].startswith("occupied")
    }
    data = {
        "tab": tab_id,
        "cwd": os.getcwd(),
        "written_at": time.time(),
        "posture": posture,
        "roles": roles,
    }
    try:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w") as fh:
            json.dump(data, fh, indent=2)
    except OSError as exc:
        print(f"4pp: could not write state file {state_path}: {exc}", file=sys.stderr)


def pane_index(panes: list[dict]) -> dict[str, dict]:
    return {p["pane_id"]: p for p in panes}


def repair_drift(panes: list[dict], agents: list[dict], state_roles: dict) -> tuple[list[str], list[str]]:
    """Reconcile labels against the recorded panel. No name heuristics: only panes this
    panel actually created are ever relabeled, and contradictory labels are cleared."""
    name_by_pane = {a["pane_id"]: (a.get("name") or "") for a in agents}
    by_id = pane_index(panes)
    authority: dict[str, str] = {}
    for role, rec in state_roles.items():
        if role not in ROLE_NAMES or not isinstance(rec, dict):
            continue
        pane_id = rec.get("pane_id")
        agent = rec.get("agent") or ""
        if pane_id in by_id and agent and name_by_pane.get(pane_id) == agent:
            authority[role] = pane_id

    fixed: list[str] = []
    cleared: list[str] = []
    for role, pane_id in authority.items():
        want = f"{LABEL_PREFIX}{role}"
        if pane_label(by_id[pane_id]) != want:
            herdr("pane", "rename", pane_id, want)
            fixed.append(f"{pane_id} relabeled {role} (agent {name_by_pane[pane_id]})")
    if not authority:
        # No records yet: labels are the only marker, so adopt them and clear nothing.
        return fixed, cleared
    authoritative_panes = set(authority.values())
    for pane in panes:
        label = pane_label(pane)
        if not label.startswith(LABEL_PREFIX):
            continue
        role = label[len(LABEL_PREFIX):]
        if pane["pane_id"] in authoritative_panes:
            continue
        # Only a real contradiction is cleared: the role is recorded on another pane.
        if role in authority:
            herdr("pane", "rename", pane["pane_id"], "--clear")
            cleared.append(f"{pane['pane_id']} label '{label}' cleared (role is recorded on {authority[role]})")
    return fixed, cleared


def main() -> int:
    rebrief, as_json, task = parse_args(sys.argv[1:])
    task = task or os.environ.get("4PP_TASK", "").strip()

    if os.environ.get("HERDR_ENV") != "1":
        die("not inside a Herdr pane (HERDR_ENV != 1). Run /4pp from a pi session inside Herdr.")
    caller_pane = os.environ.get("HERDR_PANE_ID") or die("HERDR_PANE_ID missing")
    tab_id = os.environ.get("HERDR_TAB_ID") or die("HERDR_TAB_ID missing")
    workspace_id = os.environ.get("HERDR_WORKSPACE_ID", "")

    kind = os.environ.get("4PP_KIND", "pi")
    # One namespace per tab, so two panels never overwrite each other.
    tab_dir = os.path.join(REPORT_DIR, tab_id.replace(":", "-"))
    state_path = os.path.join(tab_dir, "panel.json")
    allow_write = os.environ.get("4PP_COORDINATOR_GRANTS_WRITE") == "1"
    strict = os.environ.get("4PP_STRICT_NO_WRITE") == "1"
    if strict:
        tool_posture = (
            "Strict mode: your tools are read, grep, find and ls only. You cannot run commands and cannot write anything. "
            "Report findings; the coordinator runs and edits."
        )
    elif allow_write:
        tool_posture = (
            "The coordinator granted write access for this task only. Use it narrowly, and still never commit, push, or change git state."
        )
    else:
        tool_posture = (
            "You have no edit or write tools. Never create, modify, rename, or delete repo files, and never change git state "
            "(no add, commit, checkout, restore, reset, stash, clean, push), on your own initiative. A command the coordinator "
            "explicitly asks you to run is authorized, including its own side effects. Only the coordinator writes code; if a task "
            "needs a change, return the exact patch (file, anchor text, replacement) and the coordinator applies it."
        )
    report_rule = (
        f"Also write the same json block to {tab_dir}/<role>.json."
        if allow_write
        else "Answer in your pane only. Do not write a file. The coordinator extracts the block."
    )
    if allow_write:
        os.makedirs(tab_dir, exist_ok=True)

    panes = panes_in_tab(tab_id)
    agents = live_agents()
    state = load_state(state_path)
    state_roles = state.get("roles") or {}
    repaired, cleared = repair_drift(panes, agents, state_roles)
    if repaired or cleared:
        panes = panes_in_tab(tab_id)
    other_panes = [p for p in panes if p["pane_id"] != caller_pane]
    by_id = pane_index(panes)
    agent_name_by_pane = {a["pane_id"]: (a.get("name") or "") for a in agents}

    # 1. Reuse the recorded panel first, then any pane carrying a 4pp label, and
    #    recognize a run started from inside the panel. A labeled pane that holds a
    #    foreign agent is reported as occupied instead of being adopted.
    assigned: dict[str, dict] = {}
    for role, rec in state_roles.items():
        if role not in ROLE_NAMES or not isinstance(rec, dict):
            continue
        pane_id = rec.get("pane_id")
        agent = rec.get("agent") or ""
        if pane_id in by_id and agent and agent_name_by_pane.get(pane_id) == agent:
            assigned[role] = by_id[pane_id]
    foreign_labeled: dict[str, str] = {}
    for pane in other_panes:
        label = pane_label(pane)
        if not label.startswith(LABEL_PREFIX):
            continue
        role = label[len(LABEL_PREFIX):]
        if role not in ROLE_NAMES or role in assigned:
            continue
        name = agent_name_by_pane.get(pane["pane_id"], "")
        if name and not is_panel_agent_name(role, name):
            foreign_labeled[role] = pane["pane_id"]
            continue
        assigned[role] = pane

    caller_info = next((p for p in panes if p["pane_id"] == caller_pane), None)
    caller_label = pane_label(caller_info or {})
    if allow_write and caller_label.startswith(LABEL_PREFIX):
        die(
            "a panel pane cannot grant itself write approval. Ask the coordinator pane to run /4pp with "
            "4PP_COORDINATOR_GRANTS_WRITE=1 if that is the intent."
        )
    if caller_label.startswith(LABEL_PREFIX):
        caller_role = caller_label[len(LABEL_PREFIX):]
        if caller_role in ROLE_NAMES:
            assigned.setdefault(caller_role, caller_info)
            print(f"4pp: running from inside the panel ({caller_pane} = {caller_role}); that pane is left untouched.", file=sys.stderr)

    # 2. Build the canonical layout when the caller is alone.
    missing = [r for r in ROLE_ORDER if r not in assigned]
    if missing and not other_panes:
        right = split(caller_pane, "right", 0.33)
        col2_top = right
        col3_top = split(right, "right", 0.5)
        col2_bottom = split(col2_top, "down", 0.5)
        col3_bottom = split(col3_top, "down", 0.5)
        created = {col2_top: "contraire", col3_top: "tester", col2_bottom: "reviewer", col3_bottom: "bigpicture"}
        for pane_id, role in created.items():
            herdr("pane", "rename", pane_id, f"{LABEL_PREFIX}{role}")
            assigned[role] = {"pane_id": pane_id, "agent_status": "unknown"}
        panes = panes_in_tab(tab_id)
        other_panes = [p for p in panes if p["pane_id"] != caller_pane]

    # A pane that is labeled for a role but runs a foreign agent is left alone.
    role_failures: dict[str, dict] = {
        role: {
            "pane_id": pane_id,
            "agent": agent_name_by_pane.get(pane_id, "-"),
            "status": f"occupied: {pane_id} is labeled {LABEL_PREFIX}{role} but runs another agent",
        }
        for role, pane_id in foreign_labeled.items()
    }

    # 3. Fill remaining roles: prefer empty panes, else split the caller pane. Never
    #    take over a pane that already hosts an agent and never relabel a foreign pane.
    missing = [r for r in ROLE_ORDER if r not in assigned and r not in role_failures]
    for role in missing:
        panes = panes_in_tab(tab_id)
        used = {p["pane_id"] for p in assigned.values()}
        candidates = [
            p
            for p in panes
            if p["pane_id"] != caller_pane
            and p["pane_id"] not in used
            and not pane_label(p).startswith(LABEL_PREFIX)
            and not has_agent(p)
        ]
        if candidates:
            # top-left-most empty pane, so roles fill the grid in reading order
            target = reading_order(candidates)[0]
        else:
            # Only our own caller pane may be split. Never crowd a pane that belongs
            # to another agent or to the panel itself: report the role as failed.
            caller_rect = (by_id.get(caller_pane) or {}).get("rect") or {}
            direction = "down" if caller_rect.get("width", 0) >= caller_rect.get("height", 1) * 2 else "right"
            new_id = split(caller_pane, direction, 0.5)
            target = {"pane_id": new_id, "agent_status": "unknown"}
        herdr("pane", "rename", target["pane_id"], f"{LABEL_PREFIX}{role}")
        assigned[role] = target

    # 4. Start agents on labeled panes that hold none. Never touch an occupied pane.
    taken = {a["name"] for a in live_agents() if a.get("name")}
    agents_by_pane = {a["pane_id"]: a for a in live_agents()}
    panel: dict[str, dict] = {}
    for role in ROLE_ORDER:
        if role in role_failures:
            panel[role] = role_failures[role]
            continue
        pane = assigned[role]
        pane_id = pane["pane_id"]
        existing = agents_by_pane.get(pane_id)
        if pane_id == caller_pane:
            panel[role] = {"pane_id": pane_id, "agent": "(this session)", "status": "caller"}
            continue
        if existing and existing.get("name"):
            panel[role] = {"pane_id": pane_id, "agent": existing["name"], "status": "reused"}
            continue
        if existing:
            panel[role] = {"pane_id": pane_id, "agent": "(occupied)", "status": "occupied: pane already runs an agent"}
            continue
        name = free_agent_name(AGENT_BASES[role], taken)
        extra: list[str] = []
        if kind == "pi":
            # these flags are pi-specific; other agent kinds get their defaults
            if strict:
                extra += ["--tools", "read,grep,find,ls"]
            elif not allow_write:
                extra += ["--exclude-tools", "edit,write"]
            if os.environ.get("4PP_MODEL"):
                extra += ["--model", os.environ["4PP_MODEL"]]
            if os.environ.get("4PP_THINKING"):
                extra += ["--thinking", os.environ["4PP_THINKING"]]
        cmd = ["agent", "start", name, "--kind", kind, "--pane", pane_id, "--timeout", str(START_TIMEOUT_MS)]
        if extra:
            cmd += ["--", *extra]
        payload = herdr(*cmd, check=False)
        if payload.get("_returncode") != 0:
            err = (payload.get("error") or {}).get("message") or payload.get("raw") or "unknown error"
            panel[role] = {"pane_id": pane_id, "agent": name, "status": f"FAILED: {err}"}
            continue
        panel[role] = {"pane_id": pane_id, "agent": name, "status": "started"}

    # 5. Send role briefs.
    contract, validator = load_contract()
    ctx_base = {
        "CWD": os.getcwd(),
        "TAB_ID": tab_id,
        "CALLER_PANE": caller_pane,
        "TOOL_POSTURE": tool_posture,
        "REPORT_RULE": report_rule,
        "CONTRACT": contract,
        "VALIDATOR": validator,
        "BRIEF_VERSION": BRIEF_VERSION,
        "PEERS": ", ".join(f"{ROLE_NAMES[r]}={panel[r]['pane_id']}" for r in ROLE_ORDER),
    }
    for role in ROLE_ORDER:
        entry = panel[role]
        if entry["status"] == "caller" or entry["status"].startswith("FAILED") or entry["status"].startswith("occupied"):
            continue
        if entry["status"] == "reused" and not rebrief:
            continue
        ctx = dict(ctx_base, PANE_ID=entry["pane_id"])
        prompt = brief_for(role, ctx)
        payload = herdr(
            "agent",
            "prompt",
            entry["agent"],
            prompt,
            "--wait",
            "--timeout",
            str(PROMPT_TIMEOUT_MS),
            check=False,
        )
        if payload.get("_returncode") != 0:
            err = (payload.get("error") or {}).get("message") or payload.get("raw") or "unknown error"
            entry["brief"] = f"FAILED: {err}"
        else:
            entry["brief"] = "sent"

    # 6. Optional fan-out of a task to the whole panel.
    if task:
        for role in ROLE_ORDER:
            entry = panel[role]
            if entry["status"] == "caller" or entry["status"].startswith("FAILED") or entry["status"].startswith("occupied"):
                continue
            if entry.get("brief", "").startswith("FAILED"):
                continue
            # no --wait: fan out in parallel, the parent collects results afterwards
            herdr("agent", "prompt", entry["agent"], task, check=False)

    save_state(state_path, tab_id, panel, "write-granted" if allow_write else "coordinator-writes")

    out = {
        "tab": tab_id,
        "caller_pane": caller_pane,
        "workspace": workspace_id,
        "cwd": os.getcwd(),
        "report_dir": tab_dir,
        "state_file": state_path,
        "tool_posture": "coordinator-granted write" if allow_write else "panel cannot write (coordinator only)",
        "labels_repaired": repaired,
        "labels_cleared": cleared,
        "panel": panel,
        "task": task or None,
    }
    if as_json:
        print(json.dumps(out, indent=2))
        return 0

    print(f"4pp panel in {tab_id} (caller {caller_pane}, cwd {os.getcwd()})")
    print(f"  write rule: {'coordinator granted write for this task' if allow_write else 'coordinator writes, panel advises'}")
    for line in repaired:
        print(f"  label repaired: {line}")
    for line in cleared:
        print(f"  label cleared: {line}")
    for role in ROLE_ORDER:
        e = panel[role]
        print(f"  {ROLE_NAMES[role]:<20} {e['pane_id']:<8} {e.get('agent', '-'):<22} {e['status']} (brief: {e.get('brief', 'skipped')})")
    print(f"  panel state: {state_path}")
    print("  prompt a pane with: herdr agent prompt <agent-name> \"<task>\" --wait")
    return 0


if __name__ == "__main__":
    sys.exit(main())
