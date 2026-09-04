#!/usr/bin/env python3
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
"""Equivalence test: the website builds exactly what the command line builds.

The other three tests in here are golden-file tests, because the builder's output
is only defined by what it has already been verified to produce.  This one needs
no goldens: the command line *is* the oracle.  `site/acb_web.py` exists to hand
the same arguments to the same `cli()` and zip up what lands, so every case below
runs both and asserts they cannot be told apart -- same bytes in every file, same
warnings on stdout, same errors on stderr, same exit status.

That is the promise the website makes to someone who cannot check it themselves,
and it is the one thing about the web front end worth pinning down: the page's
own JavaScript is checked by using it, but "the zip is what acb would have
written" is not something you can see by looking.

    python3 tests/test_web_equivalence.py

Nothing here touches a browser.  Pyodide runs this same module unmodified, so
running it under CPython exercises the code the page actually uses; what it
cannot cover is the JavaScript either side of it.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _golden import BUILDER, CONFIG, REPO

sys.path.insert(0, os.path.join(REPO, "site"))
import acb_web

# The real inputs in the repo root, read and never written.  _golden.REAL_INPUTS
# has the four required ones under the command line's names; the web front end
# keys them by role and adds the optional airband file.
REAL_INPUTS = {
    "analog": "Analog__PNW-Community-260307.csv",
    "digital_others": "Digital-Others__PNW-Community-200926.csv",
    "digital_repeaters": "Digital-Repeaters__PNW-all-2026-08-29.csv",
    "talkgroups": "Talkgroups__PNW-all-2026-08-29.csv",
    "am_air": "Airband__PNW.csv",
}

DEFAULTS = {"sorting": "alpha", "nicknames": "prefix",
            "hotspot_tx_permit": "same-color-code"}

work = tempfile.mkdtemp(prefix="acb-webeq-")

# acb_web is written for the one filesystem it has in the browser, so its
# directories are module constants rather than arguments.  Pointing them at a
# temporary directory is the whole of what it takes to run it here.
acb_web.IN_DIRECTORY = os.path.join(work, "in")
acb_web.OUT_DIRECTORY = os.path.join(work, "out")
acb_web.ZIP_PATH = os.path.join(work, "codeplug.zip")


def web(options, inputs=None, sources=None):
    """Run the builder the way the page does, and unpack the zip it produced.

    Returns the parsed result plus {filename: bytes} for whatever came back.
    """
    acb_web.reset()
    for role in (inputs or REAL_INPUTS):
        source = (sources or {}).get(role) or os.path.join(REPO, REAL_INPUTS[role])
        shutil.copy(source, acb_web.input_path(role))

    result = json.loads(acb_web.build(json.dumps(dict(DEFAULTS, **options))))

    files = {}
    if result["ok"]:
        with zipfile.ZipFile(acb_web.ZIP_PATH) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
    return result, files


def cli(options, inputs=None):
    """Run the same build through builder.py, over the same input files.

    Deliberately the files acb_web was pointed at rather than copies of them, so
    that any path either side quotes in a message is the same path -- there is
    then nothing to scrub before the two outputs can be compared.
    """
    outdir = os.path.join(work, "cli-out")
    shutil.rmtree(outdir, ignore_errors=True)
    os.makedirs(outdir)

    args = [f"{acb_web.INPUT_OPTIONS[role]}={acb_web.input_path(role)}"
            for role in (inputs or REAL_INPUTS)]
    args += [f"--output-directory={outdir}", f"--config={CONFIG}",
             f"--sorting={options.get('sorting', DEFAULTS['sorting'])}",
             f"--nicknames={options.get('nicknames', DEFAULTS['nicknames'])}",
             f"--hotspot-tx-permit="
             f"{options.get('hotspot_tx_permit', DEFAULTS['hotspot_tx_permit'])}",
             f"--cps-format={options['cps_format']}"]

    done = subprocess.run([sys.executable, BUILDER] + args,
                          capture_output=True, text=True)
    files = {name: open(os.path.join(outdir, name), "rb").read()
             for name in sorted(os.listdir(outdir)) if not name.startswith(".")}
    return done, files


def compare(result, web_files, done, cli_files):
    """Every way the two runs could differ, as a list of readable problems."""
    problems = []

    if result["ok"] != (done.returncode == 0):
        problems.append(f"ok={result['ok']} but the command line exited "
                        f"{done.returncode}")
    if result["stdout"] != done.stdout:
        problems.append("stdout differs from the command line's")
    if result["stderr"] != done.stderr:
        problems.append("stderr differs from the command line's")

    # Files are only comparable when the build succeeded.  A fatal error stops
    # the builder partway through writing the channel file, so the command line
    # leaves a truncated one behind; the website hands back nothing at all,
    # which is the point -- half a codeplug is worse than none.
    if not result["ok"]:
        return problems

    # Both directions, so a file the website invents is caught as well as one it
    # loses -- a renamed output otherwise reads only as the old name missing.
    for name in sorted(set(web_files) | set(cli_files)):
        if name not in web_files:
            problems.append(f"{name}: missing from the zip")
        elif name not in cli_files:
            problems.append(f"{name}: in the zip but not written by the command line")
        elif web_files[name] != cli_files[name]:
            problems.append(f"{name}: contents differ")

    # The listing shown on the page has to agree with what the zip holds, or it
    # reports a build the visitor did not receive.
    listed = {entry["name"]: entry["size"] for entry in result["files"]}
    if listed != {name: len(data) for name, data in web_files.items()}:
        problems.append("the page's file listing disagrees with the zip")

    return problems


def matches_command_line(options, inputs=None):
    result, web_files = web(options, inputs)
    done, cli_files = cli(options, inputs)
    return compare(result, web_files, done, cli_files)


def crlf_preserved():
    """CRLF must survive the zip: the CPS wants it, text mode would strip it."""
    problems = []
    _, files = web({"cps_format": "3"})
    for name, data in sorted(files.items()):
        if data.count(b"\n") == 0 or data.count(b"\r\n") != data.count(b"\n"):
            problems.append(f"{name}: {data.count(b'\\r\\n')} CRLF "
                            f"vs {data.count(b'\\n')} LF")
    return problems


def deterministic():
    """The same inputs must produce the same zip, byte for byte.

    Entries are stamped with a fixed date for this reason; the default is the
    time of the build, which would make two identical builds differ.
    """
    web({"cps_format": "1"})
    first = open(acb_web.ZIP_PATH, "rb").read()
    with zipfile.ZipFile(acb_web.ZIP_PATH) as archive:
        stamped = [entry.filename for entry in archive.infolist()
                   if entry.date_time != acb_web.ZIP_EPOCH]

    web({"cps_format": "1"})
    second = open(acb_web.ZIP_PATH, "rb").read()

    problems = []
    # Checked directly, not just by rebuilding: the default stamp is the time of
    # the build to the second, so two builds this close together would match
    # anyway and the comparison alone would prove nothing.
    if stamped:
        problems.append("stamped with the build time rather than a fixed date: "
                        + ", ".join(stamped))
    if first != second:
        problems.append("a rebuild produced a different zip")
    return problems


def no_stale_outputs():
    """A second build must not carry the first one's files.

    Format 3 renames all four outputs, so anything left behind by a format 1
    build shows up here as a file that should not exist.
    """
    web({"cps_format": "1"})
    _, files = web({"cps_format": "3"})
    stale = sorted(name for name in files if name.islower())
    return [f"left over from the previous build: {', '.join(stale)}"] if stale else []


def bom_is_stripped():
    """A spreadsheet's UTF-8 BOM must not reach the builder.

    Left in place it arrives as part of the first header cell, and the file no
    longer parses.  The result has to match a run over the same file without one.
    """
    bom = os.path.join(work, "bom-analog.csv")
    with open(bom, "wb") as handle:
        handle.write(b"\xef\xbb\xbf" + open(
            os.path.join(REPO, REAL_INPUTS["analog"]), "rb").read())

    result, files = web({"cps_format": "1"}, sources={"analog": bom})
    if not result["ok"]:
        return ["a leading BOM broke the build"]

    plain, plain_files = web({"cps_format": "1"})
    return [] if files == plain_files else ["a leading BOM changed the output"]


def reports_failure_like_the_command_line():
    """A fatal error has to reach the page as the command line words it."""
    broken = os.path.join(work, "broken-analog.csv")
    rows = open(os.path.join(REPO, REAL_INPUTS["analog"])).read().splitlines(True)
    rows[1] = rows[1].replace(",High,", ",Massive,")
    open(broken, "w").write("".join(rows))

    result, web_files = web({"cps_format": "1"}, sources={"analog": broken})
    done, cli_files = cli({"cps_format": "1"})

    problems = compare(result, web_files, done, cli_files)
    if result["ok"]:
        problems.append("an invalid power level still built successfully")
    if "Invalid Power Level" not in result["stderr"]:
        problems.append("the reason never reached the page")

    # Nothing to download, and nothing half-written to download it from: the
    # command line leaves its partial channel file on disk, the website does not
    # offer one.
    if result.get("zip_path") or web_files:
        problems.append("a failed build still offered a zip")
    return problems


CASES = [
    ("format-0", lambda: matches_command_line({"cps_format": "0"})),
    ("format-1", lambda: matches_command_line({"cps_format": "1"})),
    ("format-2", lambda: matches_command_line({"cps_format": "2"})),
    ("format-3", lambda: matches_command_line({"cps_format": "3"})),
    ("format-4", lambda: matches_command_line({"cps_format": "4"})),
    # Airband is the optional fifth input, and only format 3 reads the result --
    # the others still write the pair, with a warning that has to carry across.
    ("no-airband", lambda: matches_command_line(
        {"cps_format": "1"}, inputs=[r for r in REAL_INPUTS if r != "am_air"])),
    ("airband-on-format-0", lambda: matches_command_line({"cps_format": "0"})),
    ("sorting-repeaters-first", lambda: matches_command_line(
        {"cps_format": "1", "sorting": "repeaters-first"})),
    ("sorting-analog-first", lambda: matches_command_line(
        {"cps_format": "1", "sorting": "analog-first"})),
    ("nicknames-off", lambda: matches_command_line(
        {"cps_format": "1", "nicknames": "off"})),
    ("nicknames-suffix-forced", lambda: matches_command_line(
        {"cps_format": "1", "nicknames": "suffix-forced"})),
    ("hotspot-always", lambda: matches_command_line(
        {"cps_format": "1", "hotspot_tx_permit": "always"})),
    ("crlf-preserved", crlf_preserved),
    ("deterministic-zip", deterministic),
    ("no-stale-outputs", no_stale_outputs),
    ("bom-stripped", bom_is_stripped),
    ("failure-reported", reports_failure_like_the_command_line),
]


def main():
    results = [(name, case()) for name, case in CASES]
    failed = [name for name, problems in results if problems]

    for name, problems in results:
        print(f"{'FAIL' if problems else 'ok  '}  {name}")
        for problem in problems:
            print(f"        {problem}")

    print(f"\n{len(results) - len(failed)}/{len(results)} cases: the website "
          f"builds what the command line builds")
    if failed:
        print("\nThe website and the command line have diverged. Both run the same\n"
              "cli(), so look at site/acb_web.py rather than at the builder.")
    return 1 if failed else 0


try:
    sys.exit(main())
finally:
    shutil.rmtree(work, ignore_errors=True)
