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
"""Regression test: discovering CPS formats from the config directory.

A format is a channel-defaults CSV, found by looking in the config directory
rather than by being listed in the code, so each case here builds a --config
directory of its own and records what the builder made of it.

The equivalence checks at the end say that a format found on disk is as good as
one that ships: a layout dropped in under a name nothing ships has to produce,
byte for byte, what the format it was copied from produces.  What they do not
say is that the derived column map matches the table the builder used to carry,
because both sides of the comparison derive their columns the same way.  That is
test_output_regression.py's job, and its goldens predate the table's removal.

    python3 tests/test_format_regression.py            # check
    python3 tests/test_format_regression.py --update   # re-record
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _golden import (CONFIG, FIXTURES, REPO, build_args, compare, digests, load,
                     report, run, save, updating)

DEFAULTS = "channel-defaults-{}.csv"
FORMAT = "format-{}.csv"


####
# Building a config directory
####

def copied(source, name):
    """Take one of the packaged channel layouts as a format of another name."""
    return lambda d: shutil.copy(os.path.join(CONFIG, DEFAULTS.format(source)),
                                 os.path.join(d, DEFAULTS.format(name)))


def copied_with_edit(source, name, old, new):
    def setup(d):
        text = open(os.path.join(CONFIG, DEFAULTS.format(source))).read()
        assert old in text, f"pattern not found in format {source}: {old!r}"
        open(os.path.join(d, DEFAULTS.format(name)), "w").write(text.replace(old, new))
    return setup


def format_file(name, content):
    return lambda d: open(os.path.join(d, FORMAT.format(name)), "w").write(content)


def raw(filename, content):
    return lambda d: open(os.path.join(d, filename), "w").write(content)


def steps(*setups):
    return lambda d: [s(d) for s in setups]


# A format 4 layout under a name nothing ships, so what comes out of it can only
# have come from the file itself.
DROP_IN = copied("4", "9")

CASES = [
    # ---- a format that is nothing but a channel layout ----
    # No format file at all: every property has to fall back to what formats 2, 3
    # and 4 share, and the column map has to come out of the header names.
    ("drop-in",             DROP_IN, "9"),

    # The same, from the oldest layout, which has neither a talkgroup ID nor a
    # DMR mode column.  Those two are the only fields allowed to be missing.
    ("drop-in-38-column",   copied("0", "9"), "9"),

    # That layout with the format file that belongs to it, which is what makes it
    # format 0 rather than a format 0 channel row in modern zones and scanlists.
    ("drop-in-with-format-file",
     steps(copied("0", "9"),
           raw(FORMAT.format("9"), open(os.path.join(CONFIG, FORMAT.format("0"))).read())),
     "9"),

    # ---- the packaged formats stay reachable through a --config of one's own ----
    # The directory holds only format 9, so answering for format 3 at all means
    # the packaged directory was read underneath it.
    ("overlay-packaged",    DROP_IN, "3"),

    # Same name as a packaged format: the user's file is the one that wins.
    ("override-packaged",   copied("0", "1"), "1"),

    # ---- format file keys ----
    ("labelled-and-tested", steps(DROP_IN, format_file("9", "label,Imaginary CPS\ntested,yes\n")), "9"),
    ("renamed-outputs",     steps(DROP_IN, format_file("9",
                                 "file.channels,Chan.CSV\nfile.zones,Zn.CSV\n"
                                 "file.scanlists,Scan.CSV\nfile.talkgroups,Tg.CSV\n")), "9"),
    ("legacy-shape",        steps(DROP_IN, format_file("9",
                                 "freq_decimals,as-is\nzone_hide,no\n"
                                 "talkgroup_notes,yes\nmember_freqs,no\n")), "9"),
    ("comments-and-blanks", steps(DROP_IN, format_file("9",
                                 "# a comment\n\nlabel,Spaced Out\n\n# another\n")), "9"),

    # ---- when the header names are not ones this build knows ----
    ("unknown-header",      copied_with_edit("4", "9", "1,Channel Name,", "1,Radio Channel Label,"), "9"),
    ("unknown-header-named", steps(copied_with_edit("4", "9", "1,Channel Name,", "1,Radio Channel Label,"),
                                   format_file("9", "column.1,name\n")), "9"),
    # An explicit nothing, for a header that means something else on this CPS.
    ("column-unmapped",     steps(DROP_IN, format_file("9", "column.55,\n")), "9"),

    # ---- format files that do not make sense ----
    ("bad-key",             steps(DROP_IN, format_file("9", "zone_hyde,yes\n")), "9"),
    ("bad-boolean",         steps(DROP_IN, format_file("9", "zone_hide,maybe\n")), "9"),
    ("bad-decimals",        steps(DROP_IN, format_file("9", "freq_decimals,lots\n")), "9"),
    ("bad-output-name",     steps(DROP_IN, format_file("9", "file.channels,../escape.csv\n")), "9"),
    ("bad-output-key",      steps(DROP_IN, format_file("9", "file.channel,Chan.CSV\n")), "9"),
    ("bad-column-key",      steps(DROP_IN, format_file("9", "column.eleven,tg_id\n")), "9"),
    ("bad-column-field",    steps(DROP_IN, format_file("9", "column.55,colour_code\n")), "9"),
    ("one-column-row",      steps(DROP_IN, format_file("9", "label\n")), "9"),

    # ---- the channel layout itself ----
    ("empty-layout",        raw(DEFAULTS.format("9"), ""), "9"),
    ("layout-short-row",    copied_with_edit("4", "9", "5,Transmit Power,High", "5,Transmit Power"), "9"),

    # ---- naming ----
    # Not a usable format name, so it is passed over rather than complained
    # about -- and asking for it then says what there actually is.
    ("illegal-name-ignored", raw(DEFAULTS.format("9 spaces"), "0,No.,REQUIRED\n"), "9 spaces"),
    ("unknown-format",      DROP_IN, "nope"),
]


def record(work, name, setup, cps_format):
    case = os.path.join(work, name)
    config = os.path.join(case, "config")
    outdir = os.path.join(case, "out")
    os.makedirs(config)
    os.makedirs(outdir)

    if setup:
        setup(config)

    args = build_args(FIXTURES, outdir, [f"--cps-format={cps_format}"], config=config)
    rc, out = run(args, {config: "<config>", case: "<case>",
                         FIXTURES: "<fixtures>", CONFIG: "<packaged>", REPO: "<repo>"})
    return {"exit": rc, "output": out, "files": digests(outdir)}


work = tempfile.mkdtemp(prefix="acb-fmtreg-")
actual = {name: record(work, name, setup, fmt) for name, setup, fmt in CASES}


####
# The derivation check: a dropped-in layout has to match the format it came from
####

_packaged = {}


def packaged_run(fmt):
    """What the packaged format of this name builds from the same fixtures."""
    if fmt not in _packaged:
        outdir = os.path.join(work, f"packaged-{fmt}")
        os.makedirs(outdir)
        run(build_args(FIXTURES, outdir, [f"--cps-format={fmt}"]), {})
        _packaged[fmt] = digests(outdir)
    return _packaged[fmt]


# Which files each dropped-in copy has to reproduce, and why it is not always all
# four.  A bare channel layout is only half of what a packaged format is: the
# other half is its format file, and without one the three files that are not the
# channel list take the modern shape instead of the format's own.  Format 4's
# format file says nothing that reaches the output, so all four have to match;
# format 0's says a great deal, so only the channel list does until it is carried
# across too.
EQUIVALENCES = (
    ("drop-in", "4", None),
    ("drop-in-38-column", "0", ("channels.csv",)),
    ("drop-in-with-format-file", "0", None),
)

equivalences = []
for case, source, only in EQUIVALENCES:
    want = packaged_run(source)
    got = actual[case]["files"]
    names = set(only) if only else want.keys() | got.keys()
    problems = [f"{name}: format {source} and the dropped-in copy differ"
                for name in sorted(names) if want.get(name) != got.get(name)]
    scope = f" ({', '.join(only)})" if only else ""
    equivalences.append((f"{case} builds what format {source} builds{scope}", problems))

shutil.rmtree(work, ignore_errors=True)

if updating():
    save("formats.json", actual)
    # Recorded or not, a derivation that has stopped matching is a failure: there
    # is nothing to re-record here, the two runs simply have to agree.
    sys.exit(report(equivalences, "derivation checks") if any(p for _, p in equivalences) else 0)

expected = load("formats.json")
results = [(name,
            ["no golden recorded for this case"] if name not in expected
            else compare(expected[name], actual[name]))
           for name, _, _ in CASES]

sys.exit(report(results + equivalences, "format-discovery cases"))
