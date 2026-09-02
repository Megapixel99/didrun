#!/usr/bin/env node
/**
 * didrun — run a command and say whether it actually did anything.
 *
 *   didrun --expect-count "(\\d+) passed" -- pytest tests/
 *   didrun --expect "ok  " -- go test ./...
 *   didrun --wrote coverage/lcov.info -- npm run coverage
 *   didrun --expect-count "(\\d+) problems?" --min 0 --expect-failure "no-unused" -- eslint src
 *
 * Exit codes: 0 ran and passed · 3 DID NOT RUN · 4 failed the wrong way ·
 * otherwise the command's own status.
 */

import process from "node:process";
import { run, report, exitCodeFor, evidence } from "../src/index.js";

function usage() {
  process.stderr.write(
    `didrun — an exit code cannot tell you whether anything happened.

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
  --timeout MS            kill the command after MS and classify anyway
  --quiet                 only print on a bad verdict
  --json                  print the result as JSON
  -h, --help

Exit: 0 ran and passed · 3 did not run · 4 failed the wrong way ·
      otherwise the command's own status.
`
  );
}

// THE FLAGS THAT SWALLOW THE NEXT ARGUMENT. `--` says which arguments are the command's.
// It does not say which of OURS are flags: `-h` is a regex to `--expect` and a path to
// `--wrote`, and reading either as a request for help printed usage and exited 0 without
// ever spawning the command, which is the same check-that-cannot-fail 0.1.3 closed one
// argument further out.
const VALUED = new Set([
  "--expect", "--expect-stdout", "--expect-stderr", "--expect-count",
  "--min", "--wrote", "--took-at-least", "--expect-failure", "--timeout",
]);

/** Is `-h`/`--help` here as OUR flag, rather than as some other flag's value? */
function wantsUsage(ours) {
  for (let i = 0; i < ours.length; i++) {
    if (ours[i] === "-h" || ours[i] === "--help") return true;
    if (VALUED.has(ours[i])) i++;   // the next argument is a value, not a flag
  }
  return false;
}

function main(argv) {
  const sep = argv.indexOf("--");
  // Only the args before `--` are didrun's own. Scanning all of argv would let a
  // `--help` belonging to the command under test print OUR usage and exit 0
  // without ever spawning it, which is exactly the kind of check that cannot fail.
  const ours = sep === -1 ? argv : argv.slice(0, sep);
  if (argv.length === 0 || wantsUsage(ours)) {
    usage();
    return argv.length === 0 ? 2 : 0;
  }
  if (sep === -1) {
    process.stderr.write("didrun: put the command after `--`\n");
    return 2;
  }
  const flags = argv.slice(0, sep);
  const command = argv.slice(sep + 1);
  if (command.length === 0) {
    process.stderr.write("didrun: nothing to run after `--`\n");
    return 2;
  }

  const predicates = [];
  let expectFailure = null;
  let timeout;
  let quiet = false;
  let asJson = false;
  let min = 1;
  const counts = [];

  // A MISSING VALUE IS COULD-NOT-RUN (2), NOT THE COMMAND'S OWN STATUS, and it is settled
  // HERE so no predicate is built from half an argument list. `value()` threw out of
  // `main`: node printed an unhandled rejection and exited 1, the code that means THE
  // WRAPPED COMMAND failed normally, so anything branching on this table read a didrun
  // usage error as a test failure. Same walk as `wantsUsage`, same table.
  for (let i = 0; i < flags.length; i++) {
    if (!VALUED.has(flags[i])) continue;
    if (i + 1 >= flags.length) {
      process.stderr.write(`didrun: ${flags[i]} needs a value\n`);
      return 2;
    }
    i++;
  }
  for (let i = 0; i < flags.length; i++) {
    const flag = flags[i];
    const value = () => {
      const v = flags[++i];
      // Unreachable: the walk above proved every valued flag has one.
      if (v === undefined) throw new Error(`${flag} needs a value`);
      return v;
    };
    switch (flag) {
      case "--expect": predicates.push(evidence.matches(value(), "output")); break;
      case "--expect-stdout": predicates.push(evidence.matches(value(), "stdout")); break;
      case "--expect-stderr": predicates.push(evidence.matches(value(), "stderr")); break;
      case "--expect-count": counts.push(value()); break;
      case "--min": min = Number(value()); break;
      case "--wrote": predicates.push(evidence.wrote(value())); break;
      case "--took-at-least": predicates.push(evidence.tookAtLeast(Number(value()))); break;
      case "--expect-failure": expectFailure = value(); break;
      case "--timeout": timeout = Number(value()); break;
      case "--quiet": quiet = true; break;
      case "--json": asJson = true; break;
      default:
        process.stderr.write(`didrun: unknown option ${flag}\n`);
        return 2;
    }
  }
  // `--min` is read after the loop so it applies however it was ordered on the command
  // line. A flag that silently means different things depending on where you put it is
  // a flag that will be wrong in somebody's CI file.
  for (const pattern of counts) predicates.push(evidence.count(pattern, { min }));

  if (predicates.length === 0) {
    process.stderr.write(
      "didrun: give at least one piece of evidence (--expect, --expect-count, " +
        "--wrote, --took-at-least).\n" +
        "        Without one, this can only report the exit code — which is the\n" +
        "        thing it exists to stop you trusting.\n"
    );
    return 2;
  }

  return run(command, { evidence: predicates, expectFailure, timeout, inherit: !asJson })
    .then((result) => {
      if (asJson) {
        process.stdout.write(JSON.stringify(result, null, 2) + "\n");
      } else if (!quiet || !result.ok) {
        process.stderr.write("\n[didrun] " + report(result) + "\n");
      }
      return exitCodeFor(result);
    })
    .catch((err) => {
      process.stderr.write(`didrun: ${err.message}\n`);
      return 2;
    });
}

Promise.resolve(main(process.argv.slice(2))).then((code) => {
  process.exitCode = code;
});
