"""The two halves agree about the vocabulary, or a CI file means two things.

`didrun` exists so a pipeline can branch on WHETHER A CHECK RAN. That branch is a state
name and an exit code, and a repository that installs the Python half in one job and the
JavaScript half in another must get the same answer from both. Two implementations that
merely resemble each other are two implementations that will disagree on the day it
matters.

Skips — loudly, with a reason — when `node` is not on PATH, so a Python-only contributor
can still run the suite. CI asserts they were not skipped, because a skipped parity test
and a passing one look identical in a tally.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(ROOT)
JS = os.path.join(REPO, "js", "src", "index.js")
sys.path.insert(0, ROOT)

import didrun  # noqa: E402

NODE = shutil.which("node")


def from_node(expression):
    script = (f"import * as m from {json.dumps(JS)};"
              f"console.log(JSON.stringify({expression}));")
    proc = subprocess.run([NODE, "--input-type=module", "-e", script],
                          capture_output=True, text=True, cwd=REPO, timeout=120)
    if proc.returncode != 0:
        raise AssertionError(f"node failed: {proc.stderr.strip()[:300]}")
    return json.loads(proc.stdout)


@unittest.skipUnless(NODE, "node is not on PATH, so the cross-half contract cannot be checked")
class TheVocabularyIsOneContract(unittest.TestCase):
    def test_the_four_state_names_are_identical(self):
        # A pipeline that greps for "did-not-run" must find it whichever half ran.
        js = from_node("[m.DID_NOT_RUN, m.RAN_AND_PASSED, m.RAN_AND_FAILED, "
                       "m.RAN_AND_FAILED_WRONGLY]")
        self.assertEqual(js, [didrun.DID_NOT_RUN, didrun.RAN_AND_PASSED,
                              didrun.RAN_AND_FAILED, didrun.RAN_AND_FAILED_WRONGLY])

    def test_the_exit_codes_are_identical(self):
        # THE ONE THAT ACTUALLY BREAKS A BUILD. `if [ $? -eq 3 ]` in a CI file has to
        # mean "did not run" in both halves or the branch is a coin flip.
        js = from_node("[m.EXIT_DID_NOT_RUN, m.EXIT_WRONG_FAILURE]")
        self.assertEqual(js, [didrun.EXIT_DID_NOT_RUN, didrun.EXIT_WRONG_FAILURE])

    def test_did_not_run_is_not_1_in_either_half(self):
        # The whole point of a separate code: "your tests failed" and "you have no
        # tests" must not collide.
        self.assertNotIn(didrun.EXIT_DID_NOT_RUN, (0, 1))
        self.assertNotEqual(didrun.EXIT_DID_NOT_RUN, didrun.EXIT_WRONG_FAILURE)

    def test_both_halves_classify_the_same_run_the_same_way(self):
        """The vocabulary agreeing is cheap; the CLASSIFIER agreeing is the claim.

        Same command, same predicate, both halves — `0 passed` on a zero exit is the
        case the whole package exists for, and it must be `did-not-run` in both.
        """
        node_state = from_node(
            "await (async () => { const r = await m.run("
            "[process.execPath, '-e', 'process.stdout.write(\"0 passed\")'],"
            "{ evidence: [m.evidence.count(/(\\\\d+) passed/)] }); return r.state; })()"
        )
        mine = didrun.run(
            [sys.executable, "-c", "import sys; sys.stdout.write('0 passed')"],
            evidence=[didrun.evidence.count(r"(\d+) passed")],
        ).state
        self.assertEqual(node_state, didrun.DID_NOT_RUN)
        self.assertEqual(mine, didrun.DID_NOT_RUN)
        self.assertEqual(node_state, mine)


# EVERY FLAG THIS TOOL ACCEPTS, and whether the parse loop swallows the next argument.
# `VALUED` decides two things at once: whether a `-h` is ours or the previous flag's
# value, and whether a flag at the end of the line is missing something. A flag added to
# the loop and forgotten in `VALUED` answers both wrongly, in the passing direction.
#
# WHAT THIS CANNOT DO is notice a flag that is in neither the loop nor this list. It reads
# valuedness out of the parse loop's own behaviour rather than out of `VALUED`, so the two
# tables cannot drift apart without failing here; a THIRD place is still needed for a flag
# nobody wrote down twice.
FLAGS = [
    "--expect", "--expect-stdout", "--expect-stderr", "--expect-count",
    "--min", "--wrote", "--took-at-least", "--expect-failure", "--timeout",
    "--quiet", "--json",
]
PROBE = "--didrun-probe-unknown"
NODE = shutil.which("node")
BIN = os.path.join(os.path.dirname(ROOT), "js", "bin", "didrun.js")


@unittest.skipUnless(NODE, "node is not on PATH")
class TheValuedFlagTableIsComplete(unittest.TestCase):
    """Does the flag swallow the next argument, and does `VALUED` know that it does?"""

    def _js(self, args):
        return subprocess.run([NODE, BIN, *args], capture_output=True, text=True,
                              timeout=120)

    def _py(self, args):
        return subprocess.run([sys.executable, "-m", "didrun.cli", *args],
                              capture_output=True, text=True, cwd=ROOT, timeout=120)

    def _swallows(self, run, flag):
        """Ask the PARSE LOOP, not the table.

        A flag that takes a value eats `PROBE`; one that does not leaves it in flag
        position, where it comes back as `unknown option`. Neither answer consults
        `VALUED`, which is what makes this an independent reading of the same fact.
        """
        out = run([flag, PROBE, "--", sys.executable, "-c", ""])
        return f"unknown option {PROBE}" not in out.stderr

    def test_both_halves_agree_about_which_flags_take_a_value(self):
        mine = {f: self._swallows(self._py, f) for f in FLAGS}
        theirs = {f: self._swallows(self._js, f) for f in FLAGS}
        self.assertEqual(mine, theirs)
        self.assertTrue(any(mine.values()), "no flag took a value, so this compares nothing")
        self.assertFalse(all(mine.values()), "every flag took a value, so does this")

    def test_the_help_scan_steps_over_exactly_the_flags_that_take_a_value(self):
        """For a valued flag, `FLAG -h` is that flag's value and the command must run.

        For a boolean one the `-h` is in flag position and IS ours, so usage must print.
        Both directions matter: a valued flag missing from `VALUED` reopens the exit-0
        bypass, and a boolean one wrongly in it swallows a `-h` somebody meant for us.
        """
        for flag in FLAGS:
            for half, run in (("python", self._py), ("javascript", self._js)):
                with self.subTest(flag=flag, half=half):
                    valued = self._swallows(run, flag)
                    out = run([flag, "-h", "--", sys.executable, "-c", ""])
                    printed = "an exit code cannot tell you" in out.stderr
                    if valued:
                        self.assertFalse(printed,
                                         f"{flag} takes a value, and its `-h` printed our "
                                         f"usage: {flag} is missing from VALUED")
                    else:
                        self.assertTrue(printed,
                                        f"{flag} takes no value, so the `-h` after it was "
                                        f"ours and usage should have printed")



@unittest.skipUnless(NODE, "node is not on PATH")
class TheCommandLineSaysTheSameThing(unittest.TestCase):
    """The usage text and the flags it describes are one contract, not two."""

    _js = TheValuedFlagTableIsComplete._js
    _py = TheValuedFlagTableIsComplete._py

    def test_the_usage_text_is_identical(self):
        """Two copies of 40 lines of flags, and a CI file is written from whichever one
        the author happened to read.

        This caught `--timeout`, which each half documented correctly and differently:
        `MS` here, `SECONDS` there, for the same flag on the same command line.
        """
        mine, theirs = self._py(["--help"]), self._js(["--help"])
        self.assertEqual(mine.returncode, 0)
        self.assertEqual(theirs.returncode, 0)
        self.assertEqual(mine.stderr, theirs.stderr)
        self.assertIn("--expect-count", mine.stderr,
                      "the usage compared here is not the flag list")

    def test_a_timeout_means_the_same_number_of_seconds_in_both_halves(self):
        """The usage text agreeing is not the flag agreeing.

        `run()` takes milliseconds in JavaScript and seconds in Python, so `--timeout 5`
        killed at 5ms in one half and 5s in the other: one command line, opposite
        verdicts, from the package whose entire subject is that a command that did not
        run must not look like one that passed.
        """
        slow = [sys.executable, "-c", "import time; time.sleep(3); print('done')"]
        quick = [sys.executable, "-c", "import time; time.sleep(0.2); print('done')"]

        # A floor no half can meet: 1 second against a 3 second command.
        for half, run in (("python", self._py), ("javascript", self._js)):
            with self.subTest(half=half, case="fires"):
                out = run(["--expect", "done", "--timeout", "1", "--", *slow])
                self.assertEqual(out.returncode, 3)

        # And a ceiling both clear: 5 seconds against a fifth of one.
        for half, run in (("python", self._py), ("javascript", self._js)):
            with self.subTest(half=half, case="does not fire"):
                out = run(["--expect", "done", "--timeout", "5", "--", *quick])
                self.assertEqual(out.returncode, 0)

    def test_a_deadline_BOUNDS_the_run_and_not_only_the_verdict(self):
        """Asserting that a timeout fires is not asserting when, and only one is the promise.

        THE TEST ABOVE PASSED WHILE THIS WAS BROKEN, which is the whole reason this one
        exists. `--timeout 2` against a five-second command took FIVE SECONDS in the
        JavaScript half and reported, accurately, that it had killed the child at two.
        The verdict was right, the exit code was right, both halves agreed, and the
        deadline had done nothing.

        Two things hid it. The case above uses a DIRECT child, and killing a direct
        child does close its pipes; the failure needs a grandchild, which is what
        `-- pytest tests/` under a shell is and what this module documents. And the
        assertion was a comparison — but a comparison cannot express a bound. Two halves
        that both overrun agree perfectly, so if the Python half had shared the defect
        this suite would have reported parity about two runs that both ignored the
        deadline. That is this family's own zero-denominator failure aimed at its own
        parity suite, so the assertion below is a flat number rather than a diff.

        The ceiling is generous because it is a bound and not a stopwatch: a loaded
        runner may take real time to start an interpreter. It still fails a deadline
        that did not bound the command at all.
        """
        # `sh -c` puts the sleep BEHIND the process that gets signalled.
        grandchild = ["sh", "-c", "sleep 20; echo done"]
        ceiling = 10.0

        for half, run in (("python", self._py), ("javascript", self._js)):
            with self.subTest(half=half):
                started = time.monotonic()
                out = run(["--expect", "done", "--timeout", "2", "--", *grandchild])
                elapsed = time.monotonic() - started
                self.assertEqual(out.returncode, 3, out.stderr)
                self.assertLess(
                    elapsed, ceiling,
                    f"{half} reported the deadline fired but took {elapsed:.1f}s to "
                    f"bound a 20s command under --timeout 2 — the signal reached the "
                    f"direct child and not the process group",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
