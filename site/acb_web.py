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
#     JS  writes a CPS format's files to staging_path(<file name>)
#     JS  calls  add_format(<those file names as JSON>)  ->  <formats, as JSON>
#     JS  calls  formats()  ->  <the CPS formats available, as JSON>
#
import contextlib
import io
import json
import os
import re
import shutil
import traceback
import zipfile

from anytone_config_builder import __version__
from anytone_config_builder.builder import (MAX_INPUT_FILE_BYTES, ConfigError, cli,
                                            load_formats)

IN_DIRECTORY = "/work/in"
OUT_DIRECTORY = "/work/out"

# Where a visitor's own CPS format goes.  Unlike the two above it is not emptied
# between builds: a format is a thing you add once and then build with, possibly
# several times, and re-picking the file for every build would be tedious for no
# safety gained.
#
# It is not kept anywhere either, though.  Pyodide's filesystem lives in the tab
# and dies with it, and nothing here reaches for IndexedDB or localStorage: the
# format CSV is the visitor's file, kept wherever they keep their other codeplug
# CSVs, and this page holds no copy of it.
CONFIG_DIRECTORY = "/work/config"

# Where the page writes a picked format file before add_format() looks at it.
# Nothing lands in CONFIG_DIRECTORY until it has been read and found good, so an
# upload that fails leaves the tab exactly as it was -- a bad file left in the
# config directory would fail every later build, on every format, until reload.
STAGING_DIRECTORY = "/work/staging"

ZIP_PATH = "/work/codeplug.zip"

# The zip format's own epoch.  See _zip_outputs().
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

# Which command line option each input file is passed as.  The four the builder
# requires come first; airband is optional, and only the one CPS that reads the
# result is going to do anything with it -- the builder says so if it will not.
INPUT_OPTIONS = {
    "analog": "--analog-csv",
    "digital_others": "--digital-others-csv",
    "digital_repeaters": "--digital-repeaters-csv",
    "talkgroups": "--talkgroups-csv",
    "am_air": "--am-air-csv",
}

REQUIRED_INPUTS = ("analog", "digital_others", "digital_repeaters", "talkgroups")

# The only two file names a visitor may add to CONFIG_DIRECTORY, and the shape of
# the name between them.  Anything else is refused: this is the one place the page
# takes a file name rather than making one up, and it decides where a file lands.
CONFIG_FILE_RE = re.compile(r"(?:channel-defaults|format)-[A-Za-z0-9_-]+\.csv\Z")

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


def _format_file_name(name):
    """`name` if it is one of a CPS format's two files, else ValueError.

    Rejects anything that is not a channel layout or a format file, which also
    rejects every name that could put the file somewhere other than where it is
    joined to: the pattern allows no dot, no slash and no separator of any other
    kind.
    """
    if not CONFIG_FILE_RE.match(name):
        raise ValueError(f"not a CPS format file name: {name}")
    return name


def config_path(name):
    """Where a CPS format file lives once add_format() has accepted it."""
    return f"{CONFIG_DIRECTORY}/{_format_file_name(name)}"


def staging_path(name):
    """Where the page writes a picked format file for add_format() to look at.

    Makes sure the directory is there to write into: the page can add a format
    before it has ever built, and reset() -- which also creates it -- runs only
    ahead of a build.
    """
    os.makedirs(STAGING_DIRECTORY, exist_ok=True)
    return f"{STAGING_DIRECTORY}/{_format_file_name(name)}"


def formats():
    """The CPS formats this build can write, for the page's format menu.

    Whatever ships with the builder, plus whatever the visitor has added to
    CONFIG_DIRECTORY.  Everything in that directory has been through
    add_format(), so this is not expected to fail; if it somehow does, the menu
    still has to say what went wrong and offer the formats that shipped.
    """
    os.makedirs(CONFIG_DIRECTORY, exist_ok=True)
    try:
        found = load_formats(CONFIG_DIRECTORY)
    except ConfigError as exc:
        return json.dumps({"ok": False, "error": str(exc).strip(),
                           "formats": _format_list(load_formats())})

    return json.dumps({"ok": True, "formats": _format_list(found)})


def add_format(names_json):
    """Take the format files the page staged into the config directory.

    `names_json` is a JSON list of the file names written to STAGING_DIRECTORY.
    Each is normalised the way an input file is -- BOM stripped, Latin-1 read as
    such -- moved into CONFIG_DIRECTORY, and the whole directory read back.  If
    the builder cannot make sense of the result, the move is undone: what was
    added is removed, and what it replaced is put back.  The visitor is told what
    was wrong, and the menu goes on offering everything that loaded before.

    Returns the same JSON as formats().
    """
    names = [_format_file_name(name) for name in json.loads(names_json)]
    os.makedirs(CONFIG_DIRECTORY, exist_ok=True)

    # What each name held before, so a failed upload can put it back.  A bad
    # channel-defaults-9.csv must not cost the visitor the good one it replaced.
    previous = {}
    for name in names:
        path = config_path(name)
        if os.path.exists(path):
            with open(path, "rb") as handle:
                previous[name] = handle.read()
        else:
            previous[name] = None

    def restore():
        for name, content in previous.items():
            path = config_path(name)
            if content is None:
                if os.path.exists(path):
                    os.remove(path)
            else:
                with open(path, "wb") as handle:
                    handle.write(content)

    try:
        for name in names:
            _normalise(staging_path(name))
            shutil.move(staging_path(name), config_path(name))
        found = load_formats(CONFIG_DIRECTORY)
    except ConfigError as exc:
        restore()
        return json.dumps({"ok": False, "error": str(exc).strip(),
                           "formats": _format_list(load_formats(CONFIG_DIRECTORY))})
    except BaseException:
        # Not one of the builder's own complaints, so something is wrong here
        # rather than in the file.  Let it reach the page as the fault it is --
        # but not with the file still in place to fail every later build.
        restore()
        raise
    finally:
        for name in names:
            if os.path.exists(staging_path(name)):
                os.remove(staging_path(name))

    return json.dumps({"ok": True, "formats": _format_list(found)})


def _format_list(found):
    return [{"name": fmt.name, "label": fmt.label, "tested": fmt.tested,
             "added": fmt.defaults_path.startswith(CONFIG_DIRECTORY + "/")}
            for fmt in found.values()]


def reset():
    """Empty the working directories.

    Called before the page writes a new set of inputs, so that a second build in
    the same tab cannot pick up a file -- input or output -- left by the first.
    CONFIG_DIRECTORY is deliberately not among them; see where it is defined.
    """
    for directory in (IN_DIRECTORY, OUT_DIRECTORY, STAGING_DIRECTORY):
        shutil.rmtree(directory, ignore_errors=True)
        os.makedirs(directory)

    os.makedirs(CONFIG_DIRECTORY, exist_ok=True)

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

    # Only when the visitor has actually added something: --config is checked,
    # and pointing it at an empty directory for every build would mean every
    # build carried a directory it had no reason to look in.
    if os.path.isdir(CONFIG_DIRECTORY) and os.listdir(CONFIG_DIRECTORY):
        argv.append(f"--config={CONFIG_DIRECTORY}")

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
