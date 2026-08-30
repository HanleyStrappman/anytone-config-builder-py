#
# Anytone config builder -- test suite.
#
# Copyright (C) 2026 Scott Robinson (AG7T)
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
# PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <https://www.gnu.org/licenses/>.
"""Shared plumbing for the golden-file regression tests.

These replace the differential tests that used to diff against the Perl original
(`anytone-config-builder.pl`, since removed).  The recorded goldens were captured
from a build that had been verified byte-identical to the Perl across all 30 flag
combinations, so they carry that verification forward.

Run a test with `--update` to re-record its goldens after an intentional change.
Read the resulting diff before committing it -- that diff is the whole point.
"""
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
BUILDER = os.path.join(REPO, "anytone_config_builder.py")
FIXTURES = os.path.join(HERE, "fixtures")
GOLDEN = os.path.join(HERE, "golden")

# The real inputs in the repo root, used as-is: the builder is never pointed at a
# modified copy of them, and never writes anywhere near them.
REAL_INPUTS = {
    "analog": "Analog__PNW-Community-260307.csv",
    "digital-others": "Digital-Others__PNW-Community-200926.csv",
    "digital-repeaters": "Digital-Repeaters__PNW-all-2026-08-29.csv",
    "talkgroups": "Talkgroups__PNW-all-2026-08-29.csv",
}


def updating():
    return "--update" in sys.argv[1:]


def scrub(text, replacements):
    """Swap machine-specific paths for stable placeholders.

    Error messages quote the paths they were given, and usage() prints argv[0],
    so without this the goldens would only ever match on one machine in one
    temporary directory.  Longest first, so a nested path can't be half-replaced.
    """
    for path, placeholder in sorted(replacements.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(path, placeholder)
    return text


def build_args(indir, outdir, extra=(), config=None):
    names = {"analog": f"{indir}/analog.csv",
             "digital-others": f"{indir}/others.csv",
             "digital-repeaters": f"{indir}/repeaters.csv",
             "talkgroups": f"{indir}/talkgroups.csv"}
    return [f"--{flag}-csv={path}" for flag, path in names.items()] + [
        f"--config={config or os.path.join(REPO, 'config')}",
        f"--output-directory={outdir}",
    ] + list(extra)


def run(args, replacements, cwd=None):
    """Run the builder and return its exit status and scrubbed combined output.

    Pass `cwd` for anything that leans on a relative path -- without --config the
    builder looks for a directory literally named "config" next to wherever it was
    invoked, so the result would otherwise depend on where you ran the test from.
    """
    p = subprocess.run([sys.executable, BUILDER] + args,
                       capture_output=True, text=True, cwd=cwd)
    return p.returncode, scrub(p.stdout + p.stderr, replacements)


def outputs(outdir):
    """The files a run actually wrote, sorted.

    Deliberately a directory listing rather than a fixed list of names: what the
    four outputs are called is a property of the CPS format, so reading it back
    from CPS_FORMATS would only prove the builder agrees with itself.  Taking
    whatever landed in the directory makes the recorded golden the assertion --
    a name that changes, appears or goes missing shows up as a diff to read.
    """
    return sorted(name for name in os.listdir(outdir) if not name.startswith("."))


def digests(outdir):
    """sha256 of each file the run generated, keyed by name."""
    out = {}
    for name in outputs(outdir):
        path = os.path.join(outdir, name)
        out[name] = hashlib.sha256(open(path, "rb").read()).hexdigest()
    return out


def load(name):
    path = os.path.join(GOLDEN, name)
    if not os.path.exists(path):
        sys.exit(f"no golden file at {path}\n"
                 f"record one with:  python3 {sys.argv[0]} --update")
    with open(path) as fh:
        return json.load(fh)


def save(name, data):
    path = os.path.join(GOLDEN, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"recorded {os.path.relpath(path, REPO)}")


def compare(expected, actual):
    """Return a list of human-readable differences between two golden records."""
    problems = []
    if expected.get("exit") != actual.get("exit"):
        problems.append(f"exit status {expected.get('exit')} -> {actual.get('exit')}")

    if expected.get("output") != actual.get("output"):
        want = (expected.get("output") or "").splitlines()
        got = (actual.get("output") or "").splitlines()
        for line in [l for l in want if l not in got]:
            problems.append(f"no longer printed: {line}")
        for line in [l for l in got if l not in want]:
            problems.append(f"newly printed:    {line}")
        if not problems or want == got:
            problems.append("output differs in line order or whitespace")

    # Both sides, so a file that appears when it shouldn't is caught too -- a
    # renamed output otherwise reads as the old name merely going missing.
    want_files = expected.get("files") or {}
    got_files = actual.get("files") or {}
    for name in sorted(want_files.keys() | got_files.keys()):
        want, got = want_files.get(name), got_files.get(name)
        if want != got:
            problems.append(f"{name}: "
                            + ("not generated" if got is None else
                               "unexpectedly generated" if want is None else
                               f"contents changed ({want[:12]} -> {got[:12]})"))
    return problems


def report(results, what):
    """Print one line per case and exit non-zero if any of them regressed."""
    failed = [name for name, problems in results if problems]
    for name, problems in results:
        print(f"{'FAIL' if problems else 'ok  '}  {name}")
        for problem in problems:
            print(f"        {problem}")
    print(f"\n{len(results) - len(failed)}/{len(results)} {what} match the recorded goldens")
    if failed:
        print("\nIf these changes are intended, re-record with --update and review the diff.")
    return 1 if failed else 0
