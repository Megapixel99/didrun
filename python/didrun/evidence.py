"""The evidence predicates: how a command proves it did something.

THIS IS THE HALF AN EXIT CODE CANNOT PROVIDE. `0` means "I did not fail", which is what
a run of ten thousand assertions and a run of nothing both report. Separating them needs
a second signal, and the only general one is something the command produced: a line of
output, a count in that output, a file it wrote, or time it spent.

Each predicate answers a `Check` rather than a boolean, because "no evidence" is a
message somebody has to act on and `False` is not one. The detail is what gets printed,
so it says what was looked for AND what was there.

Kept deliberately in step with `js/src/evidence.js`: the names, the wording of the
details and the semantics are one contract, so a CI file that moves between the two
halves does not change meaning. `python/tests/test_parity.py` asserts the parts that can
be asserted.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass


@dataclass
class Check:
    """One predicate's answer: did it hold, and what was actually there."""

    name: str
    satisfied: bool
    detail: str
    weak: bool = False


def _pick(result, where):
    if where == "stdout":
        return result.stdout
    if where == "stderr":
        return result.stderr
    return result.stdout + result.stderr


def _trim(text, limit=60):
    one = " ".join(str(text).split())
    return one[:limit] + "…" if len(one) > limit else one


def _compile(pattern):
    return pattern if isinstance(pattern, re.Pattern) else re.compile(pattern)


class Predicate:
    """A named question about a finished run. `before()` runs first when it needs to."""

    weak = False

    def before(self):
        return None

    def check(self, result, before):  # pragma: no cover - overridden
        raise NotImplementedError


class Matches(Predicate):
    """A regex the output must match. The bluntest evidence, and often enough."""

    def __init__(self, pattern, where="output"):
        self.re = _compile(pattern)
        self.where = where
        self.name = f"{where} matches {self.re.pattern}"

    def check(self, result, before):
        text = _pick(result, self.where)
        found = self.re.search(text)
        if found:
            return Check(self.name, True, f"matched {_trim(found.group(0))!r}")
        empty = "" if text.strip() else f" — {self.where} was empty"
        return Check(self.name, False,
                     f"nothing in {self.where} matched {self.re.pattern}{empty}")


class Count(Predicate):
    """A regex whose first group is a COUNT, which must be at least `minimum`.

    THE PREDICATE WORTH REACHING FOR. What makes a green run meaningless is almost
    always a zero rather than an absence: `0 passed`, `Ran 0 tests`, `0 files checked`.
    A pattern that only asked whether the LINE was printed is satisfied by exactly the
    run it is meant to catch, because the runner cheerfully prints its zero.
    """

    def __init__(self, pattern, minimum=1, where="output"):
        self.re = _compile(pattern)
        self.minimum = minimum
        self.where = where
        self.name = f"{where} reports at least {minimum} via {self.re.pattern}"

    def check(self, result, before):
        text = _pick(result, self.where)
        found = self.re.search(text)
        if not found:
            return Check(self.name, False,
                         f"nothing in {self.where} matched {self.re.pattern}, so no "
                         f"count was reported at all")
        raw = found.group(1) if found.groups() else found.group(0)
        digits = re.sub(r"[^\d-]", "", str(raw))
        try:
            n = int(digits)
        except ValueError:
            return Check(self.name, False,
                         f"matched {_trim(found.group(0))!r} but no number could be "
                         f"read from it")
        if n >= self.minimum:
            return Check(self.name, True, f"{n} (needed {self.minimum})")
        return Check(self.name, False,
                     f"reported {n}, which is below {self.minimum} — "
                     f"{_trim(found.group(0))!r}")


class Wrote(Predicate):
    """A file the command must have written DURING the run.

    "Exists" is not the check. A junit.xml left over from yesterday exists, and a runner
    that never started leaves it exactly where it was.
    """

    def __init__(self, path):
        self.path = path
        self.name = f"{path} was written during the run"

    def _snapshot(self):
        try:
            stat = os.stat(self.path)
            with open(self.path, "rb") as fh:
                data = fh.read()
            return {"exists": True, "size": stat.st_size, "mtime": stat.st_mtime,
                    "digest": hashlib.sha256(data).hexdigest()}
        except OSError:
            return {"exists": False, "size": 0, "mtime": 0, "digest": None}

    def before(self):
        return self._snapshot()

    def check(self, result, before):
        after = self._snapshot()
        if not after["exists"]:
            return Check(self.name, False,
                         f"{self.path} existed before the run and is gone"
                         if before["exists"] else f"{self.path} was never created")
        if not before["exists"]:
            return Check(self.name, True,
                         f"{self.path} was created ({after['size']} bytes)")
        if after["digest"] != before["digest"]:
            return Check(self.name, True,
                         f"{self.path} changed ({before['size']} -> {after['size']} bytes)")
        if after["mtime"] > before["mtime"]:
            return Check(self.name, True,
                         f"{self.path} was rewritten with the same content")
        return Check(self.name, False,
                     f"{self.path} is byte for byte what it was before the run — a "
                     f"stale artefact from an earlier run looks exactly like this")


class TookAtLeast(Predicate):
    """A floor on how long the command took.

    THE WEAKEST PREDICATE HERE, and it is included with that said out loud. It cannot
    prove work happened; it can only catch a suite that takes a minute finishing in nine
    milliseconds. Prefer a count when the command will give you one.
    """

    weak = True

    def __init__(self, ms):
        self.ms = ms
        self.name = f"the command took at least {ms}ms"

    def check(self, result, before):
        if result.duration_ms >= self.ms:
            return Check(self.name, True, f"{result.duration_ms}ms", weak=True)
        return Check(self.name, False,
                     f"finished in {result.duration_ms}ms, under the {self.ms}ms floor",
                     weak=True)


class Exits(Predicate):
    """The command's exit code must be one of `codes`."""

    def __init__(self, codes):
        self.codes = {codes} if isinstance(codes, int) else set(codes)
        self.name = f"exit code is one of {', '.join(str(c) for c in sorted(self.codes))}"

    def check(self, result, before):
        return Check(self.name, result.code in self.codes, f"exited {result.code}")


# Short constructors, so a caller writes `evidence.count(...)` in either language.
matches = Matches
count = Count
wrote = Wrote
took_at_least = TookAtLeast
exits = Exits
