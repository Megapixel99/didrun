# `didrun`

[![PyPI](https://img.shields.io/pypi/v/didrun?label=PyPI&color=3775A9)](https://pypi.org/project/didrun/)
[![npm](https://img.shields.io/npm/v/@megapixel99/didrun?label=npm&color=CB3837)](https://www.npmjs.com/package/@megapixel99/didrun)
[![ci](https://github.com/Megapixel99/didrun/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/Megapixel99/didrun/actions/workflows/ci.yml)
[![license MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

An exit code cannot tell you whether anything happened.

`0` means **"I did not fail."** A suite of ten thousand assertions and a suite that
collected nothing both report it, and no amount of reading the number harder will
separate them. That is not a nuisance — it is how a check silently stops checking and
nobody finds out for a year.

```sh
pip install didrun                    # the Python half
npm install -g @megapixel99/didrun    # the JavaScript half

didrun --expect-count "(\d+) passed" -- pytest tests/
didrun --expect "^ok " -- go test ./...
didrun --wrote coverage/lcov.info -- npm run coverage
```

The npm package is scoped because npm refused the bare name — *"too similar to existing
package `madrun`"* — so the two registries coordinate this under different names. The
**command is `didrun` either way**; only the install line differs, and `release.yml`
enforces that the npm name may add a scope and nothing else.

Both halves ship the same command, the same flags and the same exit codes. A CI file
should not have to ask which one is installed, and `python/tests/test_parity.py` asserts
the vocabulary they share — the four state names, the two exit codes, and that both
classify the same run identically.

```
$ go test ./...
?   	x	[no test files]
$ echo $?
0                       # <- this is the whole problem

$ didrun --expect "^ok " -- go test ./...
?   	x	[no test files]

[didrun] DID NOT RUN — there is no evidence this command did anything  (exit 0, 296ms)
  --  output matches /^ok /: nothing in output matched /^ok /

  It exited 0. That is the failure: a check that stopped checking reports exactly this.
$ echo $?
3
```

## The rule

> A check must answer separately whether it **RAN**, whether it **FAILED**, and whether
> the failure was the **RIGHT** one. Collapsing any two of those three is how every
> defect in this family happens.

So this returns four states rather than a number:

| state | means | exit |
|---|---|---|
| `did-not-run` | no evidence the command did anything — **regardless of exit 0** | **3** |
| `ran-and-passed` | evidence found, exit 0 | 0 |
| `ran-and-failed` | evidence found, non-zero exit, failure looked right | the command's own code |
| `ran-and-failed-wrongly` | it failed, but not the way you said it would | **4** |

The fourth exists because *"it failed"* is not *"my check caught something"*. A suite
that dies on a syntax error fails; so does one that caught your mutation. Scoring those
alike is the difference between a harness that works and one that reports success for a
file it never parsed.

`did-not-run` gets its own exit code and never borrows the command's — including when
the command itself failed. *"Your tests failed"* and *"you have no tests"* send you to
different places.

## Read this first: some runners already answer question one

Let them. Checked, not assumed:

| | answers "did it run"? |
|---|---|
| `pytest` | **yes** — exits 5 when it collects nothing |
| `jest`, `vitest` | **yes** — fail by default when no test matches (`--passWithNoTests` is the decision this tool exists to argue with) |
| `go test ./...` | **no** — prints `[no test files]` and exits **0**. Measured, not assumed |
| linters given a glob that matched nothing | generally no |
| any shell step in any CI file | no notion of the question at all |

If your runner is in the first two rows, you may not need this. It is for the rest.

## Evidence

At least one predicate is required. **With none, `run()` throws and the CLI exits 2** —
a tool that silently degrades into forwarding the exit code is the thing it is replacing.

| flag | evidence |
|---|---|
| `--expect REGEX` | combined output matches |
| `--expect-stdout` / `--expect-stderr` | one stream matches |
| `--expect-count REGEX` | the first capture group is a count, `>= --min` (default 1) |
| `--wrote PATH` | the file was actually written **during this run** |
| `--took-at-least MS` | a duration floor (weak — prefer a count) |

### `--expect-count` is the one that matters

The thing that makes a green run meaningless is almost always a **zero**, not an
absence: `0 passed`, `Ran 0 tests`, `0 files checked`. A pattern that only asks whether
the *line* was printed is satisfied by exactly the run it was meant to catch, because
the runner cheerfully prints its zero. Both behaviours are pinned by one test:

```js
// `0 passed in 0.01s`, exit 0
count(/(\d+) passed/)   -> did-not-run      "reported 0"
matches(/\d+ passed/)   -> ran-and-passed   // fooled, as advertised
```

### `--wrote` is not "the file exists"

A `junit.xml` left over from yesterday exists, and a runner that never started leaves it
exactly where it was. The file must be **created, changed, or rewritten during the run**
— a byte-for-byte identical artefact is reported as the stale thing it is.

## API

```python
from didrun import run, report, exit_code_for, evidence

result = run(["pytest", "tests/"],
             evidence=[evidence.count(r"(\d+) passed"), evidence.wrote("junit.xml")],
             expect_failure=r"AssertionError",   # when it fails, it must fail THIS way
             timeout=600)                        # killed and still classified

result.state    # "did-not-run" | "ran-and-passed" | "ran-and-failed" | "ran-and-failed-wrongly"
result.checks   # every predicate, with what it looked for and what it found
```

```js
import { run, report, exitCodeFor, evidence } from "didrun";

const result = await run(["pytest", "tests/"], {
  evidence: [evidence.count(/(\d+) passed/), evidence.wrote("junit.xml")],
  expectFailure: /AssertionError/,   // when it fails, it must fail THIS way
  timeout: 600_000,                  // killed and still classified
});

result.state   // "did-not-run" | "ran-and-passed" | "ran-and-failed" | "ran-and-failed-wrongly"
result.checks  // every predicate, with what it looked for and what it found
process.exitCode = exitCodeFor(result);
```

Every predicate must hold — `every`, not `some`. The report prints what was looked for
**and what was found, including when everything passed**, because a check whose output
is only a verdict is one nobody can audit.

A timeout is classified rather than swallowed: a killed check is a check that did not
finish, never one that passed.

## Prior art

Swept across **both registries** on mechanism nouns — the first pass queried npm only,
and npm-only sweeping is what nearly missed `crosshair` elsewhere in this line of work.

On npm, `keywords:no-tests` returns one package (a CRA template) and `keywords:ci-guard`
returns zero — dead tags, so wrong bucket names rather than open fields. `test-silence`
inventories *skipped* tests from git history; `jest-fail-on-console` and
`cypress-fail-fast` change what a runner does *while* it runs.

On PyPI, searched by name across the full 881,198-entry index plus web search, three
neighbours are real and none of them is this:

- **`pytest-custom-exit-code`** changes *pytest's* exit code when nothing is collected.
  That is one runner answering question one for itself — the thing this wraps, not a
  replacement for it.
- **`evidence-gate`** audits GitHub Actions **evidence bundles** after the fact: whether
  an audit trail is complete and temporally bounded. A different question, downstream.
- **`ranit`** reports which functions *in your diff* were executed by nothing, by
  intersecting a coverage database with the git diff. Function granularity via coverage,
  not an arbitrary command with a supplied predicate — and the closest thing in spirit
  to this anywhere.

Nothing found wraps an arbitrary command and asks whether it did anything.

## Limits

- **Evidence is only as good as the pattern you supply.** This does not know what your
  command should print; it makes you say so, once, where the next person can read it.
- `--took-at-least` cannot prove work happened. It is marked `[weak]` in the report and
  it is here because a suite that takes a minute finishing in 9ms is a real signal.
- It does not parse junit/TAP. `--wrote` plus `--expect-count` covers most of what that
  would buy.
- Zero dependencies in either half. Node ≥ 18, Python ≥ 3.9.

## Tests

```sh
npm test                                        # 22
python3 -m unittest discover -s python/tests    # 21, four of them the cross-half contract
```

22 JavaScript tests and 21 Python tests, no dependencies in either half. Six mutations to the source — never reporting `did-not-run`,
treating it as success, accepting one predicate instead of all, allowing a run with no
evidence, ignoring the count floor, and accepting a stale artefact — were each caught by
the test that should catch them.
