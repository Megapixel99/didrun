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

function main(argv) {
  const sep = argv.indexOf("--");
  if (argv.length === 0 || argv.includes("-h") || argv.includes("--help")) {
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

  for (let i = 0; i < flags.length; i++) {
    const flag = flags[i];
    const value = () => {
      const v = flags[++i];
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
