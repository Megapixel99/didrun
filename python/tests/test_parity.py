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


if __name__ == "__main__":
    unittest.main(verbosity=2)
