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


if __name__ == "__main__":
    unittest.main(verbosity=2)
