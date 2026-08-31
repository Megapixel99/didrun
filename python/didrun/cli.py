"""`didrun` — run a command and say whether it actually did anything.

    didrun --expect-count "(\\d+) passed" -- pytest tests/
    didrun --expect "^ok " -- go test ./...
    didrun --wrote coverage.xml -- coverage run -m pytest

Exit codes: 0 ran and passed · 3 DID NOT RUN · 4 failed the wrong way · otherwise the
command's own status.

THE FLAGS AND THE EXIT CODES ARE THE JAVASCRIPT HALF'S, deliberately. A CI file should
not have to ask which half is installed, and `python/tests/test_parity.py` asserts the
vocabulary the two share.
"""

from __future__ import annotations

import json
import sys

from . import evidence as ev
from .core import EXIT_DID_NOT_RUN, exit_code_for, report, run

USAGE = """didrun — an exit code cannot tell you whether anything happened.

  didrun [evidence...] [options] -- COMMAND...

Evidence (at least one is required — without it there is nothing to add to the
exit code, and this refuses rather than pretending):
  --expect REGEX          combined output must match
  --expect-stdout REGEX   stdout must match
  --expect-stderr REGEX   stderr must match
  --expect-count REGEX    first capture group is a count, and must be >= --min
  --min N                 the floor for --expect-count (default 1)
  --wrote PATH            the file must have been written during this run
  --took-at-least MS      a floor on the duration (weak; prefer a count)

Options:
  --expect-failure REGEX  when it fails, the output must match this or the
                          failure is scored as the WRONG one (exit 4)
  --timeout SECONDS       kill the command and classify anyway
  --quiet                 only print on a bad verdict
  --json                  print the result as JSON
  -h, --help

Exit: 0 ran and passed · 3 did not run · 4 failed the wrong way ·
      otherwise the command's own status.
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or "-h" in argv or "--help" in argv:
        sys.stderr.write(USAGE)
        return 0 if argv else 2
    if "--" not in argv:
        sys.stderr.write("didrun: put the command after `--`\n")
        return 2
    split = argv.index("--")
    flags, command = argv[:split], argv[split + 1:]
    if not command:
        sys.stderr.write("didrun: nothing to run after `--`\n")
        return 2

    predicates, counts = [], []
    expect_failure = timeout = None
    minimum, quiet, as_json = 1, False, False

    i = 0
    while i < len(flags):
        flag = flags[i]

        def value():
            nonlocal i
            i += 1
            if i >= len(flags):
                raise SystemExit(f"didrun: {flag} needs a value")
            return flags[i]

        if flag == "--expect":
            predicates.append(ev.matches(value(), "output"))
        elif flag == "--expect-stdout":
            predicates.append(ev.matches(value(), "stdout"))
        elif flag == "--expect-stderr":
            predicates.append(ev.matches(value(), "stderr"))
        elif flag == "--expect-count":
            counts.append(value())
        elif flag == "--min":
            minimum = int(value())
        elif flag == "--wrote":
            predicates.append(ev.wrote(value()))
        elif flag == "--took-at-least":
            predicates.append(ev.took_at_least(int(value())))
        elif flag == "--expect-failure":
            expect_failure = value()
        elif flag == "--timeout":
            timeout = float(value())
        elif flag == "--quiet":
            quiet = True
        elif flag == "--json":
            as_json = True
        else:
            sys.stderr.write(f"didrun: unknown option {flag}\n")
            return 2
        i += 1

    # `--min` is applied after the loop so it works however it was ordered on the
    # command line. A flag that silently means different things depending on where you
    # put it is a flag that will be wrong in somebody's CI file.
    for pattern in counts:
        predicates.append(ev.count(pattern, minimum=minimum))

    if not predicates:
        sys.stderr.write(
            "didrun: give at least one piece of evidence (--expect, --expect-count,\n"
            "        --wrote, --took-at-least).\n"
            "        Without one, this can only report the exit code — which is the\n"
            "        thing it exists to stop you trusting.\n"
        )
        return 2

    try:
        result = run(command, evidence=predicates, expect_failure=expect_failure,
                     timeout=timeout)
    except (OSError, FileNotFoundError) as exc:
        sys.stderr.write(f"didrun: cannot run {command[0]!r} ({exc})\n")
        return 2

    if as_json:
        json.dump({
            "command": result.command,
            "state": result.state,
            "code": result.code,
            "duration_ms": result.duration_ms,
            "killed": result.killed,
            "checks": [{"name": c.name, "satisfied": c.satisfied,
                        "detail": c.detail, "weak": c.weak} for c in result.checks],
        }, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        # The command's own output first, then the verdict, so the verdict is the last
        # thing on the screen.
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if not quiet or not result.ok:
            sys.stderr.write("\n[didrun] " + report(result) + "\n")
    return exit_code_for(result)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
