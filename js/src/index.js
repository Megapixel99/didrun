/**
 * didrun — an exit code cannot tell you whether anything happened.
 *
 * `0` means "I did not fail". A suite of ten thousand assertions and a suite that
 * collected nothing both report it, and no amount of reading the number harder will
 * separate them. That is not a nuisance: it is how a check silently stops checking and
 * nobody finds out for a year.
 *
 * The rule this implements is one sentence:
 *
 *   A check must answer separately whether it RAN, whether it FAILED, and whether the
 *   failure was the RIGHT one. Collapsing any two of those three is how every defect in
 *   this family happens.
 *
 * So this returns four states rather than a number:
 *
 *   did-not-run           no evidence the command did anything — REGARDLESS of exit 0
 *   ran-and-passed        evidence found, exit 0
 *   ran-and-failed        evidence found, non-zero exit, and the failure looked right
 *   ran-and-failed-wrongly  it failed, but not in the way you said it would
 *
 * The fourth exists because "it failed" is not "my check caught something". A suite
 * that dies on a syntax error fails; so does one that caught your mutation. Scoring
 * those alike is the difference between a harness that works and one that reports
 * success for a file it never parsed.
 *
 * WHAT THIS IS NOT FOR. Several runners already answer the first question for
 * themselves and you should let them: `pytest` exits 5 when it collects nothing, and
 * `jest` and `vitest` fail by default when no test matches (`--passWithNoTests` turns
 * that off, and turning it on is the decision this tool exists to argue with). Reach
 * for this where nothing answers it: `go test ./...` prints `[no test files]` and exits
 * 0 — verified, not assumed — as do most linters given a glob that matched nothing, and
 * every shell step ever written.
 */

import { spawn } from "node:child_process";
import * as evidence from "./evidence.js";

export const DID_NOT_RUN = "did-not-run";
export const RAN_AND_PASSED = "ran-and-passed";
export const RAN_AND_FAILED = "ran-and-failed";
export const RAN_AND_FAILED_WRONGLY = "ran-and-failed-wrongly";

// DID-NOT-RUN GETS ITS OWN EXIT CODE and never borrows the command's. Folding it into
// 1 would put "your tests failed" and "you have no tests" in the same bucket, which are
// the two states this whole module exists to keep apart.
export const EXIT_DID_NOT_RUN = 3;
export const EXIT_WRONG_FAILURE = 4;

export { evidence };

/**
 * Run `command`, gather evidence, and classify.
 *
 * @param {string[]} command argv, e.g. ["pytest", "tests/"]
 * @param {object} options
 * @param {Array} options.evidence predicates from `./evidence.js`; at least one, or
 *   this cannot answer the question it exists to answer and says so.
 * @param {RegExp|string} [options.expectFailure] when the command fails, its output
 *   must match this or the failure is the WRONG one.
 * @param {number} [options.timeout] milliseconds; the child is killed and the run is
 *   still classified, because a timed-out check is a check that did not finish rather
 *   than one that passed.
 * @returns {Promise<object>} the result, including `state`.
 */
export async function run(command, options = {}) {
  const {
    evidence: predicates = [],
    expectFailure = null,
    timeout = undefined,
    cwd = undefined,
    env = undefined,
    inherit = false,
  } = options;

  if (!Array.isArray(command) || command.length === 0) {
    throw new TypeError("run() needs a command as an array of arguments");
  }
  if (predicates.length === 0) {
    // REFUSING IS THE POINT. With no predicate this would forward the exit code and
    // call it an answer, which is precisely the behaviour it is replacing — a tool
    // that silently degrades into the thing it exists to fix is worse than no tool.
    throw new TypeError(
      "run() needs at least one evidence predicate; without one it can only report " +
        "the exit code, which is what it exists to stop you trusting"
    );
  }

  const before = predicates.map((p) => (p.before ? p.before() : null));
  const started = Date.now();
  const raw = await spawnCollect(command, { timeout, cwd, env, inherit });
  const result = {
    command,
    ...raw,
    durationMs: Date.now() - started,
  };

  const checks = predicates.map((predicate, i) => {
    const outcome = predicate.check(result, before[i]);
    return { name: predicate.name, weak: !!predicate.weak, ...outcome };
  });
  const ran = checks.every((c) => c.satisfied);

  let state;
  if (!ran) {
    state = DID_NOT_RUN;
  } else if (result.code === 0 && !result.killed) {
    state = RAN_AND_PASSED;
  } else if (expectFailure) {
    const re = evidence.toRegExp(expectFailure);
    state = re.test(result.stdout + result.stderr)
      ? RAN_AND_FAILED
      : RAN_AND_FAILED_WRONGLY;
  } else {
    state = RAN_AND_FAILED;
  }

  return { ...result, checks, state, ok: state === RAN_AND_PASSED };
}

/** The process exit code this result should produce. */
export function exitCodeFor(result) {
  switch (result.state) {
    case DID_NOT_RUN:
      return EXIT_DID_NOT_RUN;
    case RAN_AND_FAILED_WRONGLY:
      return EXIT_WRONG_FAILURE;
    case RAN_AND_PASSED:
      return 0;
    default:
      // A real failure keeps the command's own status, so an existing pipeline that
      // reads it keeps working.
      return result.code === 0 ? 1 : result.code;
  }
}

/** What to print. It always says what was looked for, including when everything passed. */
export function report(result) {
  const lines = [];
  const verdict = {
    [DID_NOT_RUN]: "DID NOT RUN — there is no evidence this command did anything",
    [RAN_AND_PASSED]: "ran, and passed",
    [RAN_AND_FAILED]: "ran, and failed",
    [RAN_AND_FAILED_WRONGLY]:
      "FAILED THE WRONG WAY — it failed, but not for the reason you named",
  }[result.state];
  lines.push(`${verdict}  (exit ${result.code}${result.killed ? ", killed" : ""}, ${result.durationMs}ms)`);
  for (const c of result.checks) {
    const mark = c.satisfied ? "  ok  " : "  --  ";
    lines.push(`${mark}${c.name}: ${c.detail}${c.weak && c.satisfied ? "  [weak]" : ""}`);
  }
  if (result.state === DID_NOT_RUN && result.code === 0) {
    lines.push("");
    lines.push(
      "  It exited 0. That is the failure: a check that stopped checking reports " +
        "exactly this."
    );
  }
  return lines.join("\n");
}

function spawnCollect(command, { timeout, cwd, env, inherit }) {
  return new Promise((resolve, reject) => {
    const child = spawn(command[0], command.slice(1), {
      cwd,
      env: env ? { ...process.env, ...env } : process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let killed = false;
    let timer = null;

    child.stdout.on("data", (d) => {
      stdout += d;
      if (inherit) process.stdout.write(d);
    });
    child.stderr.on("data", (d) => {
      stderr += d;
      if (inherit) process.stderr.write(d);
    });
    if (timeout) {
      timer = setTimeout(() => {
        killed = true;
        child.kill("SIGKILL");
      }, timeout);
    }
    child.on("error", (err) => {
      if (timer) clearTimeout(timer);
      reject(err);
    });
    child.on("close", (code, signal) => {
      if (timer) clearTimeout(timer);
      resolve({
        stdout,
        stderr,
        // A signalled death has no exit code; 128+n is the shell's convention and
        // keeps the number comparable with what a pipeline would have seen.
        code: code === null ? 128 + (signalNumber(signal) || 0) : code,
        signal,
        killed,
      });
    });
  });
}

function signalNumber(signal) {
  return { SIGKILL: 9, SIGTERM: 15, SIGINT: 2, SIGHUP: 1 }[signal] || 0;
}
