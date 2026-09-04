#
# Anytone config builder -- the Python half of the web front end.
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
#
# This runs inside Pyodide, in the visitor's browser.  It does as little as it
# can get away with: the build itself is `builder.cli()`, the very same entry
# point the `acb` console script calls, so the page cannot drift away from the
# command line as the builder changes.
#
# Everything crossing the JavaScript boundary is a string or a file in the
# Emscripten filesystem -- no object conversion, nothing to get subtly wrong:
#
#     JS  writes the CSVs to input_path(<role>)
#     JS  calls  build(<options as JSON>)  ->  <result as JSON>
#     JS  reads the zip back from the "zip_path" the result names
#
import contextlib
import io
import json
import os
import shutil
import traceback
import zipfile

from anytone_config_builder import __version__
from anytone_config_builder.builder import MAX_INPUT_FILE_BYTES, cli

IN_DIRECTORY = "/work/in"
OUT_DIRECTORY = "/work/out"
ZIP_PATH = "/work/codeplug.zip"

# The zip format's own epoch.  See _zip_outputs().
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

# Which command line option each input file is passed as.  The four the builder
# requires come first; airband is optional and only format 3 reads the result.
INPUT_OPTIONS = {
    "analog": "--analog-csv",
    "digital_others": "--digital-others-csv",
    "digital_repeaters": "--digital-repeaters-csv",
    "talkgroups": "--talkgroups-csv",
    "am_air": "--am-air-csv",
}

REQUIRED_INPUTS = ("analog", "digital_others", "digital_repeaters", "talkgroups")

# Spreadsheets write a UTF-8 BOM, which would otherwise arrive as part of the
# first field.  Latin-1 decodes any byte at all, so it is the backstop rather
# than a guess -- the builder's inputs are meant to be plain ASCII, and a file
# that isn't will fail its own validation with a message naming the line.
INPUT_ENCODINGS = ("utf-8-sig", "latin-1")


def input_path(role):
    """Where the page should write the file for `role`.

    Exported so the JavaScript never hardcodes a path of its own; this module
    stays the one place that decides where inputs live.
    """
    if role not in INPUT_OPTIONS:
        raise ValueError(f"unknown input role: {role}")
    return f"{IN_DIRECTORY}/{role}.csv"


def reset():
    """Empty the working directories.

    Called before the page writes a new set of inputs, so that a second build in
    the same tab cannot pick up a file -- input or output -- left by the first.
    """
    for directory in (IN_DIRECTORY, OUT_DIRECTORY):
        shutil.rmtree(directory, ignore_errors=True)
        os.makedirs(directory)

    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)


def _normalise(path):
    """Rewrite an uploaded file as UTF-8, without its BOM."""
    with open(path, "rb") as handle:
        raw = handle.read()

    for encoding in INPUT_ENCODINGS:
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    # newline="" so the file keeps the line endings it arrived with; the csv
    # module reads either, and rewriting them here would be a change the command
    # line doesn't make.
    with open(path, "w", newline="", encoding="utf-8") as handle:
        handle.write(text)


def _zip_outputs():
    """Zip everything the builder wrote, and say what went in.

    Listing the directory rather than naming the files keeps this correct for
    all five CPS formats -- format 3 calls them Channel.CSV and friends -- and
    for the airband pair, which appears only when --am-air-csv was given.
    """
    names = sorted(os.listdir(OUT_DIRECTORY))
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            # A fixed timestamp rather than the default "now", so that the same
            # inputs and options always produce the same zip, byte for byte.
            # Two builds are then comparable by checksum, which is the easiest
            # way to tell whether anything actually changed.
            entry = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
            entry.compress_type = zipfile.ZIP_DEFLATED

            # Binary, deliberately.  csv_writer() ends every line CRLF because
            # that is what the CPS wants; reading these back as text would
            # translate them and hand the visitor files their CPS may reject.
            with open(f"{OUT_DIRECTORY}/{name}", "rb") as handle:
                archive.writestr(entry, handle.read())

    with open(ZIP_PATH, "wb") as handle:
        handle.write(buffer.getvalue())

    return [{"name": name,
             "size": os.path.getsize(f"{OUT_DIRECTORY}/{name}")}
            for name in names]


def _result(ok, **fields):
    return json.dumps(dict(ok=ok, version=__version__, **fields))


def build(options_json):
    """Run the builder over whatever the page has written to IN_DIRECTORY.

    Returns JSON.  `ok` reports whether files were produced, which is not the
    same as "nothing to say": an over-long name is reported on stderr and the
    build carries on and succeeds, so the page shows stderr either way and lets
    the exit code decide what it means.
    """
    options = json.loads(options_json)

    present = [role for role in INPUT_OPTIONS if os.path.exists(input_path(role))]
    missing = [role for role in REQUIRED_INPUTS if role not in present]
    if missing:
        return _result(False, stdout="", stderr="",
                       error="Missing required input files: " + ", ".join(missing))

    # Ahead of _normalise(), which reads a whole file into memory: the page checks
    # the same limit before it writes anything, so reaching this means the file
    # grew or arrived some other way, but the wasm heap is small enough to be
    # worth refusing here too rather than trusting the caller.
    for role in present:
        size = os.path.getsize(input_path(role))
        if size > MAX_INPUT_FILE_BYTES:
            limit_mb = MAX_INPUT_FILE_BYTES // (1024 * 1024)
            return _result(False, stdout="", stderr="",
                           error=f"The {role} file is {size} bytes, over the "
                                 f"{limit_mb}MB limit.")

    for role in present:
        _normalise(input_path(role))

    argv = [f"{INPUT_OPTIONS[role]}={input_path(role)}" for role in present]
    argv += [
        f"--output-directory={OUT_DIRECTORY}",
        f"--sorting={options['sorting']}",
        f"--nicknames={options['nicknames']}",
        f"--hotspot-tx-permit={options['hotspot_tx_permit']}",
        f"--cps-format={options['cps_format']}",
    ]

    stdout, stderr = io.StringIO(), io.StringIO()
    crash = None

    try:
        # report_error() looks sys.stderr up on each call and warning() is a
        # plain print(), so redirecting the two streams captures both without
        # the builder needing to know it is not on a terminal.
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = cli(argv)
    except SystemExit as exc:
        # usage() exits rather than returning.  The page builds the argv itself
        # so this should be unreachable, which is exactly why it is worth
        # catching -- unhandled, it would surface as a hung button.
        exit_code = exc.code if isinstance(exc.code, int) else 255
    except Exception:
        exit_code = 255
        crash = traceback.format_exc()

    if exit_code != 0 or crash is not None:
        return _result(False, stdout=stdout.getvalue(), stderr=stderr.getvalue(),
                       exit_code=exit_code, crash=crash)

    return _result(True, stdout=stdout.getvalue(), stderr=stderr.getvalue(),
                   exit_code=exit_code, files=_zip_outputs(), zip_path=ZIP_PATH)
