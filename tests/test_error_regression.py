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
"""Regression test: what the builder reports on malformed input.

Each case copies the minimal fixture set, applies one mutation, and records the
exit status and every message produced.  The fixtures are the smallest inputs
that still exercise all three readers; the repo's real CSVs are never touched.

    python3 tests/test_error_regression.py            # check
    python3 tests/test_error_regression.py --update   # re-record
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _golden import (FIXTURES, REPO, build_args, compare, digests, load, report,
                     run, save, updating)


def edit(fname, old, new, count=1):
    def mutate(d):
        path = os.path.join(d, fname)
        text = open(path).read()
        assert old in text, f"{fname}: pattern not found: {old!r}"
        open(path, "w").write(text.replace(old, new, count))
    return mutate


def write(fname, content):
    return lambda d: open(os.path.join(d, fname), "w").write(content)


def rm(fname):
    return lambda d: os.remove(os.path.join(d, fname))


def both(*mutations):
    return lambda d: [m(d) for m in mutations]


ANALOG_ROW = "APRS - Analog,146.500 aprs,25K,High,146.5,146.5,Off,Off,Off"
OTHERS_ROW = "Simplex,Sim V01  145.790,High,145.79,145.79,1,Local 1,1,Group Call,Always"
REPEATER_ROW = "Ariel/Ariel VHF;ARA,,High,147.4125,146.4125,1,1,2,1"

# Format 3 is the one that actually reads the airband pair, so the airband cases
# use it and their output is the airband error alone, not a format warning too.
AIRBAND_ARGS = ["--cps-format=3", "--am-air-csv={case}/airband.csv"]

CASES = [
    # ---- header validation ----
    ("hdr-analog-wrong",    edit("analog.csv", "Zone,Channel Name,Bandwidth", "Zone,Chanel Name,Bandwidth"), None),
    ("hdr-others-wrong",    edit("others.csv", "Color Code,Talk Group", "Colour Code,Talk Group"), None),
    ("hdr-repeaters-wrong", edit("repeaters.csv", "Zone Name,Comment,Power", "Zone,Comment,Power"), None),
    ("hdr-analog-short",    edit("analog.csv", ",CTCSS Encode,TX Prohibit", ",CTCSS Encode"), None),

    # ---- extra columns where no matrix extractor exists ----
    ("analog-extra-column", edit("analog.csv", ANALOG_ROW, ANALOG_ROW + ",extra"), None),
    ("others-extra-column", edit("others.csv", OTHERS_ROW, OTHERS_ROW + ",extra"), None),

    # ---- field value validation ----
    ("bad-power-analog",    edit("analog.csv", ",25K,High,146.5", ",25K,Massive,146.5"), None),
    ("bad-bandwidth",       edit("analog.csv", ",25K,High,146.5", ",50K,High,146.5"), None),
    ("bad-freq-analog",     edit("analog.csv", ",High,146.5,146.5,", ",High,1465,146.5,"), None),
    ("bad-freq-nonnumeric", edit("analog.csv", ",High,146.5,146.5,", ",High,abc,146.5,"), None),
    ("bad-ctcss",           edit("analog.csv", "146.5,146.5,Off,Off,Off", "146.5,146.5,Off,999,Off"), None),
    ("bad-tx-prohibit",     edit("analog.csv", "Off,Off,Off", "Off,Off,Yes"), None),
    ("bad-color-code",      edit("others.csv", "145.79,145.79,1,Local 1", "145.79,145.79,17,Local 1"), None),
    ("bad-timeslot",        edit("others.csv", "Local 1,1,Group Call", "Local 1,3,Group Call"), None),
    ("bad-call-type",       edit("others.csv", "1,Group Call,Always", "1,Broadcast Call,Always"), None),
    ("bad-tx-permit",       edit("others.csv", "Group Call,Always", "Group Call,Whenever"), None),
    ("bad-power-repeater",  edit("repeaters.csv", ",,High,147.4125", ",,Extreme,147.4125"), None),
    ("bad-color-repeater",  edit("repeaters.csv", "147.4125,146.4125,1,", "147.4125,146.4125,-1,"), None),
    ("bad-matrix-timeslot", edit("repeaters.csv", REPEATER_ROW, "Ariel/Ariel VHF;ARA,,High,147.4125,146.4125,1,3,2,1"), None),

    # ---- length limits: reported, then truncated to fit, and the build goes on ----
    ("long-zone-analog",    edit("analog.csv", "APRS - Analog,146.500", "APRS - Analog Zone XYZ,146.500"), None),
    ("long-chan-name",      edit("analog.csv", ",146.500 aprs,", ",146.500 aprs long name,"), None),
    ("long-zone-repeater",  edit("repeaters.csv", "Ariel/Ariel VHF;ARA", "Ariel/Ariel VHF Long;ARA"), None),
    ("long-talkgroup",      both(edit("talkgroups.csv", "Local 1,3181", "Local 1 Very Long Name,3181"),
                                 edit("repeaters.csv", ",Local 1,PNW 2", ",Local 1 Very Long Name,PNW 2"),
                                 edit("others.csv", ",Local 1,1,", ",Local 1 Very Long Name,1,")), None),
    ("chan-name-no-fit",    edit("repeaters.csv", "Ariel/Ariel VHF;ARA", "AriellllllllllVHF"), None),

    # ---- talkgroup semantics ----
    ("unknown-talkgroup",   edit("others.csv", ",Local 1,1,Group Call", ",Nowhere 9,1,Group Call"), None),
    ("unknown-tg-matrix",   edit("repeaters.csv", ",Local 1,PNW 2,Parrot 1", ",Nowhere 9,PNW 2,Parrot 1"), None),
    ("truncation-collision", both(edit("talkgroups.csv", "Local 1,3181",
                                       "Local 1 Northwest A,3181\nLocal 1 Northwest B,3182"),
                                  edit("repeaters.csv", ",Local 1,PNW 2", ",Local 1 Northwest A,PNW 2"),
                                  edit("others.csv", ",Local 1,1,", ",Local 1 Northwest B,1,")), None),
    ("tg-call-type-conflict", edit("repeaters.csv", REPEATER_ROW,
                                   "Ariel/Ariel VHF;ARA,,High,147.4125,146.4125,1,1P,2,1"), None),

    # ---- command line / mode validation ----
    ("bad-sorting",         None, ["--sorting=random"]),
    ("bad-hotspot",         None, ["--hotspot-tx-permit=maybe"]),
    ("bad-nicknames",       None, ["--nicknames=sometimes"]),

    # ---- airband ----
    # The only airband conditions that stop the run.  Handing the file to a format
    # that cannot read it is a warning, not an error, and is covered in the args test.
    ("airband-bad-header",  edit("airband.csv", "Zone,Channel Name,Frequency",
                                 "Zone,Name,Frequency"), AIRBAND_ARGS),
    ("airband-bad-freq",    edit("airband.csv", "ASOS,135.675", "ASOS,not-a-number"),
                            AIRBAND_ARGS),
    ("airband-freq-clash",  edit("airband.csv", "AM Zone 2,Pulllman Unicom,122.8",
                                 "AM Zone 2,Pulllman Unicom,118.1"), AIRBAND_ARGS),
    ("airband-long-name",   edit("airband.csv", "ASOS,135.675",
                                 "ASOS Pullman Regional,135.675"), AIRBAND_ARGS),
    ("airband-missing",     rm("airband.csv"), AIRBAND_ARGS),

    # ---- missing / unreadable files ----
    ("missing-analog",      rm("analog.csv"), None),
    ("missing-talkgroups",  rm("talkgroups.csv"), None),
    ("missing-repeaters",   rm("repeaters.csv"), None),
    ("empty-analog",        write("analog.csv", ""), None),
]


def record(work, name, mutate, extra):
    case = os.path.join(work, name)
    shutil.copytree(FIXTURES, case)
    if mutate:
        mutate(case)
    outdir = os.path.join(case, "out")
    os.makedirs(outdir)
    # {case} lets a case point a flag at its own copy of the fixtures, which only
    # exists once the copytree above has run.
    args = [a.format(case=case) for a in (extra or [])]
    rc, out = run(build_args(case, outdir, args),
                  {case: "<in>", REPO: "<repo>"})
    return {"exit": rc, "output": out, "files": digests(outdir)}


work = tempfile.mkdtemp(prefix="acb-errreg-")
actual = {name: record(work, name, mutate, extra) for name, mutate, extra in CASES}
shutil.rmtree(work, ignore_errors=True)

if updating():
    save("errors.json", actual)
    sys.exit(0)

expected = load("errors.json")
results = [(name,
            [f"no golden recorded for this case"] if name not in expected
            else compare(expected[name], actual[name]))
           for name, _, _ in CASES]
sys.exit(report(results, "malformed-input cases"))
