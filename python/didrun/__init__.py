r"""didrun — an exit code cannot tell you whether anything happened.

    from didrun import run, evidence
    result = run(["pytest", "tests/"], evidence=[evidence.count(r"(\d+) passed")])
    result.state   # "did-not-run" | "ran-and-passed" | "ran-and-failed" | ...
"""

from . import evidence
from .core import (
    DID_NOT_RUN,
    EXIT_DID_NOT_RUN,
    EXIT_WRONG_FAILURE,
    RAN_AND_FAILED,
    RAN_AND_FAILED_WRONGLY,
    RAN_AND_PASSED,
    Result,
    exit_code_for,
    report,
    run,
)

__all__ = ["run", "report", "exit_code_for", "evidence", "Result",
           "DID_NOT_RUN", "RAN_AND_PASSED", "RAN_AND_FAILED", "RAN_AND_FAILED_WRONGLY",
           "EXIT_DID_NOT_RUN", "EXIT_WRONG_FAILURE"]
__version__ = "0.1.1"
