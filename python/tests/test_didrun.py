"""The claims, and the controls that make each one falsifiable."""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # python/, which is where the package lives
sys.path.insert(0, ROOT)

from didrun import (  # noqa: E402
    DID_NOT_RUN,
    EXIT_DID_NOT_RUN,
    EXIT_WRONG_FAILURE,
    RAN_AND_FAILED,
    RAN_AND_FAILED_WRONGLY,
    RAN_AND_PASSED,
    evidence,
    exit_code_for,
    report,
    run,
)


def says(text, code=0):
    """A command that prints `text` and exits `code`."""
    return [sys.executable, "-c",
            f"import sys; sys.stdout.write({text!r}); sys.exit({code})"]


class ExitZeroIsNotEvidence(unittest.TestCase):
    def test_a_command_that_exits_0_having_done_nothing_is_DID_NOT_RUN(self):
        result = run(says("", 0), evidence=[evidence.matches(r"\d+ passed")])
        self.assertEqual(result.code, 0, "the command really did exit 0")
        self.assertEqual(result.state, DID_NOT_RUN)
        self.assertEqual(exit_code_for(result), EXIT_DID_NOT_RUN)
        self.assertIn("It exited 0. That is the failure", report(result))

    def test_the_same_command_with_evidence_is_ran_and_passed(self):
        # The control. Without it, an implementation that always said DID NOT RUN would
        # satisfy the test above.
        result = run(says("41 passed\n", 0), evidence=[evidence.matches(r"\d+ passed")])
        self.assertEqual(result.state, RAN_AND_PASSED)
        self.assertEqual(exit_code_for(result), 0)

    def test_a_real_failure_keeps_the_command_s_own_exit_code(self):
        result = run(says("3 passed, 1 failed\n", 7),
                     evidence=[evidence.matches(r"\d+ passed")])
        self.assertEqual(result.state, RAN_AND_FAILED)
        self.assertEqual(exit_code_for(result), 7, "a pipeline reads this number")

    def test_DID_NOT_RUN_outranks_the_command_s_failure_too(self):
        # "Your tests failed" and "you have no tests" send you to different places.
        result = run(says("Traceback: boom\n", 2),
                     evidence=[evidence.matches(r"\d+ passed")])
        self.assertEqual(result.state, DID_NOT_RUN)
        self.assertEqual(exit_code_for(result), EXIT_DID_NOT_RUN)


class WasTheFailureTheRightOne(unittest.TestCase):
    def test_a_failure_that_does_not_match_is_scored_WRONG(self):
        result = run(says("1 passed\nSyntaxError: unexpected token\n", 1),
                     evidence=[evidence.matches(r"\d+ passed")],
                     expect_failure=r"AssertionError")
        self.assertEqual(result.state, RAN_AND_FAILED_WRONGLY)
        self.assertEqual(exit_code_for(result), EXIT_WRONG_FAILURE)

    def test_a_failure_that_matches_is_an_ordinary_failure(self):
        result = run(says("1 passed\nAssertionError: 1 != 2\n", 1),
                     evidence=[evidence.matches(r"\d+ passed")],
                     expect_failure=r"AssertionError")
        self.assertEqual(result.state, RAN_AND_FAILED)


class TheCountPredicate(unittest.TestCase):
    def test_zero_passed_is_DID_NOT_RUN_even_though_the_line_matched(self):
        # THE SUBTLETY THIS PREDICATE EXISTS FOR. A pattern that only asked whether the
        # line was printed is satisfied by exactly the run it is meant to catch.
        zero = run(says("0 passed in 0.01s\n", 0),
                   evidence=[evidence.count(r"(\d+) passed")])
        self.assertEqual(zero.state, DID_NOT_RUN)
        self.assertIn("reported 0", zero.checks[0].detail)

        naive = run(says("0 passed in 0.01s\n", 0),
                    evidence=[evidence.matches(r"\d+ passed")])
        self.assertEqual(naive.state, RAN_AND_PASSED,
                         "the naive predicate is fooled, as advertised")

    def test_a_count_with_no_number_is_refused_rather_than_guessed_at(self):
        result = run(says("many passed\n", 0),
                     evidence=[evidence.count(r"(\w+) passed")])
        self.assertEqual(result.state, DID_NOT_RUN)
        self.assertIn("no number could be read", result.checks[0].detail)

    def test_a_missing_count_says_so_differently_from_a_zero_count(self):
        result = run(says("nothing to see\n", 0),
                     evidence=[evidence.count(r"(\d+) passed")])
        self.assertIn("no count was reported at all", result.checks[0].detail)


class TheWrotePredicate(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="didrun-")
        self.artefact = os.path.join(self.dir, "junit.xml")

    def test_a_stale_artefact_from_an_earlier_run_is_not_evidence(self):
        with open(self.artefact, "w") as fh:
            fh.write("<testsuite/>")
        result = run(says("done\n", 0), evidence=[evidence.wrote(self.artefact)])
        self.assertEqual(result.state, DID_NOT_RUN)
        self.assertIn("byte for byte what it was", result.checks[0].detail)

    def test_a_file_the_command_actually_wrote_is_evidence(self):
        with open(self.artefact, "w") as fh:
            fh.write("<testsuite/>")
        cmd = [sys.executable, "-c",
               f"open({self.artefact!r}, 'w').write('<testsuite tests=\"3\"/>')"]
        result = run(cmd, evidence=[evidence.wrote(self.artefact)])
        self.assertEqual(result.state, RAN_AND_PASSED)
        self.assertIn("changed", result.checks[0].detail)

    def test_a_file_that_never_appears_is_named_as_never_created(self):
        result = run(says("done\n", 0), evidence=[evidence.wrote(self.artefact)])
        self.assertEqual(result.state, DID_NOT_RUN)
        self.assertIn("never created", result.checks[0].detail)


class RefusalsAndEdges(unittest.TestCase):
    def test_with_no_evidence_it_refuses_rather_than_forwarding_the_exit_code(self):
        with self.assertRaises(TypeError) as caught:
            run(says("hi\n", 0), evidence=[])
        self.assertIn("at least one evidence predicate", str(caught.exception))

    def test_a_timeout_is_classified_not_swallowed(self):
        result = run([sys.executable, "-c", "import time; time.sleep(5)"],
                     evidence=[evidence.matches("done")], timeout=0.3)
        self.assertTrue(result.killed)
        self.assertEqual(result.state, DID_NOT_RUN, "a killed check did not pass")

    def test_every_predicate_must_hold_not_just_one(self):
        result = run(says("5 passed\n", 0),
                     evidence=[evidence.matches("passed"), evidence.matches("coverage")])
        self.assertEqual(result.state, DID_NOT_RUN)
        self.assertEqual(sum(1 for c in result.checks if c.satisfied), 1)

    def test_the_report_says_what_was_looked_for_even_when_all_passed(self):
        result = run(says("5 passed\n", 0), evidence=[evidence.count(r"(\d+) passed")])
        text = report(result)
        self.assertIn("ok", text)
        self.assertIn("5 (needed 1)", text)

    def test_a_weak_predicate_is_marked_weak(self):
        result = run(says("x\n", 0), evidence=[evidence.took_at_least(0)])
        self.assertIn("[weak]", report(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
