import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
  run,
  report,
  exitCodeFor,
  evidence,
  DID_NOT_RUN,
  RAN_AND_PASSED,
  RAN_AND_FAILED,
  RAN_AND_FAILED_WRONGLY,
  EXIT_DID_NOT_RUN,
  EXIT_WRONG_FAILURE,
} from "../src/index.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "didrun.js");
const NODE = process.execPath;

/** A command that prints `text` and exits `code`. */
function says(text, code = 0) {
  return [NODE, "-e", `process.stdout.write(${JSON.stringify(text)});process.exit(${code})`];
}

// --------------------------------------------------------------------------- //
// The flagship: exit 0 is not evidence.
// --------------------------------------------------------------------------- //

test("a command that exits 0 having done nothing is DID NOT RUN", async () => {
  const result = await run(says("", 0), {
    evidence: [evidence.matches(/\d+ passed/)],
  });
  assert.equal(result.code, 0, "the command really did exit 0");
  assert.equal(result.state, DID_NOT_RUN);
  assert.equal(exitCodeFor(result), EXIT_DID_NOT_RUN);
  assert.match(report(result), /It exited 0\. That is the failure/);
});

test("the same command with evidence is ran-and-passed", async () => {
  // The control. Without it, an implementation that always said DID NOT RUN would
  // satisfy the test above.
  const result = await run(says("41 passed\n", 0), {
    evidence: [evidence.matches(/\d+ passed/)],
  });
  assert.equal(result.state, RAN_AND_PASSED);
  assert.equal(exitCodeFor(result), 0);
});

test("a real failure keeps the command's own exit code", async () => {
  const result = await run(says("3 passed, 1 failed\n", 7), {
    evidence: [evidence.matches(/\d+ passed/)],
  });
  assert.equal(result.state, RAN_AND_FAILED);
  assert.equal(exitCodeFor(result), 7, "an existing pipeline reads this number");
});

test("DID NOT RUN outranks the command's failure too", async () => {
  // A command that both failed AND produced no evidence is still DID NOT RUN: "your
  // tests failed" and "you have no tests" send you to different places.
  const result = await run(says("Traceback: boom\n", 2), {
    evidence: [evidence.matches(/\d+ passed/)],
  });
  assert.equal(result.state, DID_NOT_RUN);
  assert.equal(exitCodeFor(result), EXIT_DID_NOT_RUN);
});

// --------------------------------------------------------------------------- //
// The third question: was the failure the RIGHT one?
// --------------------------------------------------------------------------- //

test("a failure that does not match expectFailure is scored WRONG", async () => {
  const result = await run(says("1 passed\nSyntaxError: unexpected token\n", 1), {
    evidence: [evidence.matches(/\d+ passed/)],
    expectFailure: /AssertionError/,
  });
  assert.equal(result.state, RAN_AND_FAILED_WRONGLY);
  assert.equal(exitCodeFor(result), EXIT_WRONG_FAILURE);
});

test("a failure that matches expectFailure is an ordinary failure", async () => {
  const result = await run(says("1 passed\nAssertionError: 1 != 2\n", 1), {
    evidence: [evidence.matches(/\d+ passed/)],
    expectFailure: /AssertionError/,
  });
  assert.equal(result.state, RAN_AND_FAILED);
});

// --------------------------------------------------------------------------- //
// The count predicate, which is the one that matters.
// --------------------------------------------------------------------------- //

test("`0 passed` is DID NOT RUN even though the line matched", async () => {
  // THE SUBTLETY THIS PREDICATE EXISTS FOR. A pattern that only asked whether the line
  // was printed is satisfied by exactly the run it is meant to catch, because the
  // runner cheerfully prints its zero.
  const zero = await run(says("0 passed in 0.01s\n", 0), {
    evidence: [evidence.count(/(\d+) passed/)],
  });
  assert.equal(zero.state, DID_NOT_RUN);
  assert.match(zero.checks[0].detail, /reported 0/);

  const naive = await run(says("0 passed in 0.01s\n", 0), {
    evidence: [evidence.matches(/\d+ passed/)],
  });
  assert.equal(naive.state, RAN_AND_PASSED, "the naive predicate is fooled, as advertised");
});

test("a count with no number in it is refused rather than guessed at", async () => {
  const result = await run(says("many passed\n", 0), {
    evidence: [evidence.count(/(\w+) passed/)],
  });
  assert.equal(result.state, DID_NOT_RUN);
  assert.match(result.checks[0].detail, /no number could be read/);
});

test("a missing count line says so differently from a zero count", async () => {
  const result = await run(says("nothing to see\n", 0), {
    evidence: [evidence.count(/(\d+) passed/)],
  });
  assert.match(result.checks[0].detail, /no count was reported at all/);
});

// --------------------------------------------------------------------------- //
// The `wrote` predicate: existing is not evidence.
// --------------------------------------------------------------------------- //

test("a stale artefact from an earlier run is not evidence", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "didrun-"));
  const artefact = path.join(dir, "junit.xml");
  fs.writeFileSync(artefact, "<testsuite/>");
  const result = await run(says("done\n", 0), { evidence: [evidence.wrote(artefact)] });
  assert.equal(result.state, DID_NOT_RUN);
  assert.match(result.checks[0].detail, /byte for byte what it was/);
});

test("a file the command actually wrote is evidence", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "didrun-"));
  const artefact = path.join(dir, "junit.xml");
  fs.writeFileSync(artefact, "<testsuite/>");
  const cmd = [
    NODE, "-e",
    `require("fs").writeFileSync(${JSON.stringify(artefact)}, "<testsuite tests='3'/>")`,
  ];
  const result = await run(cmd, { evidence: [evidence.wrote(artefact)] });
  assert.equal(result.state, RAN_AND_PASSED);
  assert.match(result.checks[0].detail, /changed/);
});

test("a file that never appears is named as never created", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "didrun-"));
  const result = await run(says("done\n", 0), {
    evidence: [evidence.wrote(path.join(dir, "absent.xml"))],
  });
  assert.equal(result.state, DID_NOT_RUN);
  assert.match(result.checks[0].detail, /never created/);
});

// --------------------------------------------------------------------------- //
// Refusals and edges.
// --------------------------------------------------------------------------- //

test("with no evidence at all it refuses instead of forwarding the exit code", async () => {
  await assert.rejects(
    () => run(says("hi\n", 0), { evidence: [] }),
    /at least one evidence predicate/
  );
});

test("a timeout is classified, not swallowed", async () => {
  const result = await run([NODE, "-e", "setTimeout(()=>{}, 5000)"], {
    evidence: [evidence.matches(/done/)],
    timeout: 200,
  });
  assert.equal(result.killed, true);
  assert.equal(result.state, DID_NOT_RUN, "a killed check did not pass");
});

test("every predicate must hold, not just one", async () => {
  const result = await run(says("5 passed\n", 0), {
    evidence: [evidence.matches(/passed/), evidence.matches(/coverage/)],
  });
  assert.equal(result.state, DID_NOT_RUN);
  assert.equal(result.checks.filter((c) => c.satisfied).length, 1);
});

test("the report says what was looked for even when everything passed", async () => {
  const result = await run(says("5 passed\n", 0), {
    evidence: [evidence.count(/(\d+) passed/)],
  });
  const text = report(result);
  assert.match(text, /ok/);
  assert.match(text, /5 \(needed 1\)/, "the denominator is printed, not just a verdict");
});

test("a weak predicate is marked weak in the report", async () => {
  const result = await run(says("x\n", 0), { evidence: [evidence.tookAtLeast(0)] });
  assert.match(report(result), /\[weak\]/);
});

// --------------------------------------------------------------------------- //
// The CLI.
// --------------------------------------------------------------------------- //

function cli(args) {
  return new Promise((resolve) => {
    execFile(NODE, [BIN, ...args], (err, stdout, stderr) => {
      resolve({ code: err ? err.code ?? 0 : 0, stdout, stderr });
    });
  });
}

test("the CLI exits 3 on did-not-run and 0 on a real pass", async () => {
  const bad = await cli(["--expect-count", "(\\d+) passed", "--",
                         NODE, "-e", "process.stdout.write('0 passed')"]);
  assert.equal(bad.code, EXIT_DID_NOT_RUN);
  assert.match(bad.stderr, /DID NOT RUN/);

  const good = await cli(["--expect-count", "(\\d+) passed", "--",
                          NODE, "-e", "process.stdout.write('9 passed')"]);
  assert.equal(good.code, 0);
});

test("the CLI refuses to run with no evidence flag", async () => {
  const r = await cli(["--", NODE, "-e", "0"]);
  assert.equal(r.code, 2);
  assert.match(r.stderr, /at least one piece of evidence/);
});

test("--min applies however it is ordered on the command line", async () => {
  // A flag that means different things depending on where you put it will be wrong in
  // somebody's CI file. Both orderings must agree.
  const after = await cli(["--expect-count", "(\\d+) passed", "--min", "5", "--",
                           NODE, "-e", "process.stdout.write('3 passed')"]);
  const before = await cli(["--min", "5", "--expect-count", "(\\d+) passed", "--",
                            NODE, "-e", "process.stdout.write('3 passed')"]);
  assert.equal(after.code, EXIT_DID_NOT_RUN);
  assert.equal(before.code, EXIT_DID_NOT_RUN);
});

test("--json prints a machine-readable result", async () => {
  const r = await cli(["--json", "--expect-count", "(\\d+) passed", "--",
                       NODE, "-e", "process.stdout.write('2 passed')"]);
  const parsed = JSON.parse(r.stdout);
  assert.equal(parsed.state, RAN_AND_PASSED);
  assert.equal(parsed.checks.length, 1);
});

test("the command is required after --", async () => {
  const r = await cli(["--expect", "x", "--"]);
  assert.equal(r.code, 2);
});

test("a `--help` after `--` belongs to the command, not to didrun", async () => {
  // The bug this replaces: the help scan read the whole of argv, so `-- CMD --help`
  // printed didrun's OWN usage and exited 0 without ever spawning CMD. That makes the
  // most natural check you could write about a CLI — that it ships and prints its usage
  // — pass unconditionally, including against a binary that does not exist.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "didrun-"));
  const speaks = path.join(dir, "speaks.js");
  const mute = path.join(dir, "mute.js");
  fs.writeFileSync(speaks, "process.stdout.write('usage: tool [--json]');");
  fs.writeFileSync(mute, "process.exit(0);");

  const good = await cli(["--expect", "usage: tool", "--", NODE, speaks, "--help"]);
  assert.equal(good.code, 0);
  assert.doesNotMatch(good.stderr, /an exit code cannot tell you/,
                      "didrun printed its own usage instead of running the command");

  // And the half that was missing: it has to be able to fail.
  const bad = await cli(["--expect", "usage: tool", "--", NODE, mute, "--help"]);
  assert.equal(bad.code, EXIT_DID_NOT_RUN);

  // `-h` is the same hazard.
  const short = await cli(["--expect", "usage: tool", "--", NODE, mute, "-h"]);
  assert.equal(short.code, EXIT_DID_NOT_RUN);
});

test("didrun's own -h and --help still print usage", async () => {
  for (const flag of ["-h", "--help"]) {
    const r = await cli([flag]);
    assert.equal(r.code, 0);
    assert.match(r.stderr, /an exit code cannot tell you/);
  }
  // Before the separator, among real flags, it is still didrun's.
  const mixed = await cli(["--expect", "x", "-h", "--", NODE, "-e", "0"]);
  assert.equal(mixed.code, 0);
  assert.match(mixed.stderr, /an exit code cannot tell you/);
});
