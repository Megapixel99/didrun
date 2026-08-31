/**
 * The evidence predicates: how a command proves it did something.
 *
 * THIS IS THE HALF AN EXIT CODE CANNOT PROVIDE. `0` means "I did not fail", which is
 * what a run of ten thousand assertions and a run of nothing both report. Separating
 * them needs a second signal, and the only general one is something the command
 * produced: a line of output, a count in that output, a file it wrote, or time it
 * spent.
 *
 * Each predicate answers `{ satisfied, detail }` rather than a boolean, because "no
 * evidence" is a message somebody has to act on and `false` is not one. The detail is
 * what gets printed, so it says what was looked for AND what was there.
 */

import fs from "node:fs";
import crypto from "node:crypto";

/** A regex the combined output must match. The bluntest evidence, and often enough. */
export function matches(pattern, where = "output") {
  const re = toRegExp(pattern);
  return {
    name: `${where} matches ${re}`,
    check(result) {
      const text = pick(result, where);
      const m = text.match(re);
      return m
        ? { satisfied: true, detail: `matched ${JSON.stringify(trim(m[0]))}` }
        : {
            satisfied: false,
            detail:
              `nothing in ${where} matched ${re}` +
              (text.trim() ? "" : ` — ${where} was empty`),
          };
    },
  };
}

/**
 * A regex whose first capture group is a COUNT, which must be at least `min`.
 *
 * `--expect-count "(\d+) passed"` is the predicate worth reaching for, because the
 * thing that makes a green run meaningless is almost always a zero rather than an
 * absence: `0 passed`, `Ran 0 tests`, `0 files checked`. A pattern that only asked
 * whether the LINE was printed would be satisfied by exactly the run it is meant to
 * catch.
 */
export function count(pattern, { min = 1, where = "output" } = {}) {
  const re = toRegExp(pattern);
  return {
    name: `${where} reports at least ${min} via ${re}`,
    check(result) {
      const text = pick(result, where);
      const m = text.match(re);
      if (!m) {
        return {
          satisfied: false,
          detail: `nothing in ${where} matched ${re}, so no count was reported at all`,
        };
      }
      const raw = m[1] === undefined ? m[0] : m[1];
      const n = Number.parseInt(String(raw).replace(/[^\d-]/g, ""), 10);
      if (!Number.isFinite(n)) {
        return {
          satisfied: false,
          detail: `matched ${JSON.stringify(trim(m[0]))} but no number could be read from it`,
        };
      }
      return n >= min
        ? { satisfied: true, detail: `${n} (needed ${min})` }
        : {
            satisfied: false,
            detail: `reported ${n}, which is below ${min} — ${JSON.stringify(trim(m[0]))}`,
          };
    },
  };
}

/**
 * A file the command must have written during the run.
 *
 * "Exists" is not the check. A junit.xml left over from yesterday exists, and a runner
 * that never started leaves it exactly where it was — so the file must be NEWER than
 * the moment the command started, or have different content than it did.
 */
export function wrote(path) {
  return {
    name: `${path} was written during the run`,
    before() {
      return snapshot(path);
    },
    check(result, before) {
      const after = snapshot(path);
      if (!after.exists) {
        return {
          satisfied: false,
          detail: before.exists
            ? `${path} existed before the run and is gone`
            : `${path} was never created`,
        };
      }
      if (!before.exists) {
        return { satisfied: true, detail: `${path} was created (${after.size} bytes)` };
      }
      if (after.digest !== before.digest) {
        return {
          satisfied: true,
          detail: `${path} changed (${before.size} -> ${after.size} bytes)`,
        };
      }
      if (after.mtimeMs > before.mtimeMs) {
        return { satisfied: true, detail: `${path} was rewritten with the same content` };
      }
      return {
        satisfied: false,
        detail:
          `${path} is byte for byte what it was before the run — a stale artefact ` +
          `from an earlier run looks exactly like this`,
      };
    },
  };
}

/**
 * A floor on how long the command took.
 *
 * THE WEAKEST PREDICATE HERE, and it is included with that said out loud. It cannot
 * prove work happened; it can only catch the case where a suite that takes a minute
 * finished in nine milliseconds, which is a real and common shape of "the glob matched
 * nothing". Prefer a count when the command will give you one.
 */
export function tookAtLeast(ms) {
  return {
    name: `the command took at least ${ms}ms`,
    weak: true,
    check(result) {
      return result.durationMs >= ms
        ? { satisfied: true, detail: `${result.durationMs}ms` }
        : {
            satisfied: false,
            detail: `finished in ${result.durationMs}ms, under the ${ms}ms floor`,
          };
    },
  };
}

/** The command's exit code must be one of `codes`. */
export function exits(codes) {
  const wanted = new Set([].concat(codes));
  return {
    name: `exit code is one of ${[...wanted].join(", ")}`,
    check(result) {
      return wanted.has(result.code)
        ? { satisfied: true, detail: `exited ${result.code}` }
        : { satisfied: false, detail: `exited ${result.code}` };
    },
  };
}

// --------------------------------------------------------------------------- //

function pick(result, where) {
  if (where === "stdout") return result.stdout;
  if (where === "stderr") return result.stderr;
  return result.stdout + result.stderr;
}

export function toRegExp(pattern) {
  if (pattern instanceof RegExp) return pattern;
  return new RegExp(pattern);
}

function trim(s, n = 60) {
  const one = String(s).replace(/\s+/g, " ").trim();
  return one.length > n ? one.slice(0, n) + "…" : one;
}

function snapshot(path) {
  try {
    const stat = fs.statSync(path);
    const data = fs.readFileSync(path);
    return {
      exists: true,
      size: stat.size,
      mtimeMs: stat.mtimeMs,
      digest: crypto.createHash("sha256").update(data).digest("hex"),
    };
  } catch {
    return { exists: false, size: 0, mtimeMs: 0, digest: null };
  }
}
