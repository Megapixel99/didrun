"""didrun — an exit code cannot tell you whether anything happened.

`0` means "I did not fail". A suite of ten thousand assertions and a suite that
collected nothing both report it, and no amount of reading the number harder will
separate them. That is not a nuisance: it is how a check silently stops checking and
nobody finds out for a year.

The rule this implements is one sentence:

    A check must answer separately whether it RAN, whether it FAILED, and whether the
    failure was the RIGHT one. Collapsing any two of those three is how every defect in
    this family happens.

WHAT THIS IS NOT FOR. Several runners already answer the first question for themselves
and you should let them: `pytest` exits 5 when it collects nothing, and `jest` and
`vitest` fail by default when no test matches. Reach for this where nothing answers it:
`go test ./...` prints `[no test files]` and exits 0 — verified, not assumed — as do most
linters given a glob that matched nothing, and every shell step ever written.

THE STATE NAMES AND EXIT CODES ARE SHARED WITH THE JAVASCRIPT HALF, deliberately. A CI
file branches on these, and it should not have to ask which half is installed.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field

from . import evidence
from .evidence import Check

DID_NOT_RUN = "did-not-run"
RAN_AND_PASSED = "ran-and-passed"
RAN_AND_FAILED = "ran-and-failed"
RAN_AND_FAILED_WRONGLY = "ran-and-failed-wrongly"

# DID-NOT-RUN GETS ITS OWN EXIT CODE and never borrows the command's. Folding it into 1
# would put "your tests failed" and "you have no tests" in the same bucket, which are the
# two states this whole module exists to keep apart.
EXIT_DID_NOT_RUN = 3
EXIT_WRONG_FAILURE = 4


@dataclass
class Result:
    command: list
    stdout: str
    stderr: str
    code: int
    duration_ms: int
    killed: bool = False
    checks: list = field(default_factory=list)
    state: str = ""

    @property
    def ok(self):
        return self.state == RAN_AND_PASSED


def run(command, evidence=(), expect_failure=None, timeout=None, cwd=None, env=None):
    """Run `command`, gather evidence, and classify.

    `evidence` is a sequence of predicates from `didrun.evidence`; at least one is
    required. REFUSING IS THE POINT: with none this could only forward the exit code,
    which is the behaviour it is replacing, and a tool that silently degrades into the
    thing it exists to fix is worse than no tool.
    """
    if not command:
        raise TypeError("run() needs a command as a list of arguments")
    predicates = list(evidence)
    if not predicates:
        raise TypeError(
            "run() needs at least one evidence predicate; without one it can only "
            "report the exit code, which is what it exists to stop you trusting"
        )

    before = [p.before() for p in predicates]
    started = time.monotonic()
    killed = False
    try:
        proc = subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout, cwd=cwd, env=env)
        code, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as expired:
        # `subprocess.run` has already killed the child by the time this is caught. A
        # timed-out check is a check that did not finish rather than one that passed.
        killed = True
        code = 124  # the conventional timeout status, as `timeout(1)` uses
        out = (expired.stdout or b"").decode(errors="replace") if expired.stdout else ""
        err = (expired.stderr or b"").decode(errors="replace") if expired.stderr else ""
    duration = int((time.monotonic() - started) * 1000)

    result = Result(command=list(command), stdout=out, stderr=err, code=code,
                    duration_ms=duration, killed=killed)
    result.checks = [p.check(result, b) for p, b in zip(predicates, before)]
    ran = all(c.satisfied for c in result.checks)

    if not ran:
        result.state = DID_NOT_RUN
    elif code == 0 and not killed:
        result.state = RAN_AND_PASSED
    elif expect_failure:
        pattern = (expect_failure if isinstance(expect_failure, re.Pattern)
                   else re.compile(expect_failure))
        result.state = (RAN_AND_FAILED if pattern.search(out + err)
                        else RAN_AND_FAILED_WRONGLY)
    else:
        result.state = RAN_AND_FAILED
    return result


def exit_code_for(result):
    """The process exit code this result should produce."""
    if result.state == DID_NOT_RUN:
        return EXIT_DID_NOT_RUN
    if result.state == RAN_AND_FAILED_WRONGLY:
        return EXIT_WRONG_FAILURE
    if result.state == RAN_AND_PASSED:
        return 0
    # A real failure keeps the command's own status, so an existing pipeline that reads
    # it keeps working.
    return 1 if result.code == 0 else result.code


def report(result):
    """What to print. It always says what was looked for, including when all passed."""
    verdict = {
        DID_NOT_RUN: "DID NOT RUN — there is no evidence this command did anything",
        RAN_AND_PASSED: "ran, and passed",
        RAN_AND_FAILED: "ran, and failed",
        RAN_AND_FAILED_WRONGLY:
            "FAILED THE WRONG WAY — it failed, but not for the reason you named",
    }[result.state]
    lines = [f"{verdict}  (exit {result.code}"
             f"{', killed' if result.killed else ''}, {result.duration_ms}ms)"]
    for c in result.checks:
        mark = "  ok  " if c.satisfied else "  --  "
        weak = "  [weak]" if c.weak and c.satisfied else ""
        lines.append(f"{mark}{c.name}: {c.detail}{weak}")
    if result.state == DID_NOT_RUN and result.code == 0:
        lines.append("")
        lines.append("  It exited 0. That is the failure: a check that stopped checking "
                     "reports exactly this.")
    return "\n".join(lines)


__all__ = ["run", "report", "exit_code_for", "evidence", "Result", "Check",
           "DID_NOT_RUN", "RAN_AND_PASSED", "RAN_AND_FAILED", "RAN_AND_FAILED_WRONGLY",
           "EXIT_DID_NOT_RUN", "EXIT_WRONG_FAILURE"]
