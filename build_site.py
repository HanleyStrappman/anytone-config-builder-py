#!/usr/bin/env python3
#
# Anytone config builder -- assembles the web front end into site-build/.
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
# Python rather than a shell script on purpose: building the wheel already needs
# Python, the standard library covers everything this does including the Pyodide
# vendoring, and "Python 3 and nothing else" then holds for the website too --
# on Windows as much as on macOS and Linux.
#
#     python3 build_site.py                  # site-build/, Pyodide from the CDN
#     python3 build_site.py --with-pyodide   # ... with Pyodide served locally
#
import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
DIST = ROOT / "dist"
BUILD = ROOT / "site-build"

# Pinned rather than floating: a Pyodide upgrade changes the Python underneath
# the builder, and that is a thing to do deliberately and re-test, not to
# receive silently because a CDN moved on.
PYODIDE_VERSION = "0.29.2"
PYODIDE_CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
PYODIDE_TARBALL = (f"https://github.com/pyodide/pyodide/releases/download/"
                   f"{PYODIDE_VERSION}/pyodide-core-{PYODIDE_VERSION}.tar.bz2")

# The working PNW files in the repo root, offered on the page as a starting
# point.  Matched by prefix because the names carry a date that moves.
EXAMPLE_PATTERNS = {
    "analog": "Analog__*.csv",
    "digital_others": "Digital-Others__*.csv",
    "digital_repeaters": "Digital-Repeaters__*.csv",
    "talkgroups": "Talkgroups__*.csv",
    "am_air": "Airband__*.csv",
}


def fail(message):
    sys.stderr.write(f"ERROR: {message}\n")
    sys.exit(1)


def package_version():
    """Read __version__ without importing the package."""
    for line in (ROOT / "anytone_config_builder" / "__init__.py").read_text().splitlines():
        if line.startswith("__version__"):
            return line.split('"')[1]
    fail("Couldn't find __version__ in anytone_config_builder/__init__.py")


def build_wheel():
    """Build a fresh wheel, and return the path to it.

    Always rebuilt: the whole point of keeping the site in this repo is that the
    page cannot end up serving a builder older than the checkout it came from.
    """
    for stale in DIST.glob("*.whl"):
        stale.unlink()

    print("Building the wheel…")
    result = subprocess.run([sys.executable, "-m", "build", "--wheel"],
                            cwd=ROOT)
    if result.returncode != 0:
        fail("`python -m build --wheel` failed. If the module is missing:\n"
             "         python3 -m pip install build")

    wheels = sorted(DIST.glob("*.whl"))
    if len(wheels) != 1:
        fail(f"expected exactly one wheel in {DIST}, found {len(wheels)}")
    return wheels[0]


def copy_examples():
    """Copy the PNW CSVs in, and return the role -> relative path map."""
    examples = {}
    (BUILD / "examples").mkdir(parents=True)

    for role, pattern in EXAMPLE_PATTERNS.items():
        matches = sorted(ROOT.glob(pattern))
        if not matches:
            print(f"  no example matched {pattern}, skipping {role}")
            continue
        if len(matches) > 1:
            print(f"  {pattern} matched {len(matches)} files, using {matches[0].name}")

        shutil.copy2(matches[0], BUILD / "examples" / matches[0].name)
        examples[role] = f"./examples/{matches[0].name}"

    return examples


def vendor_pyodide():
    """Download the Pyodide core build and serve it from the site itself.

    Only the core is needed -- 6MB against the full distribution's 392MB --
    because the builder is unpacked straight onto sys.path rather than installed
    with micropip, so none of the bundled packages are wanted.
    """
    print(f"Downloading Pyodide {PYODIDE_VERSION}…")
    with tempfile.TemporaryDirectory() as scratch:
        archive = Path(scratch) / "pyodide.tar.bz2"
        urllib.request.urlretrieve(PYODIDE_TARBALL, archive)

        with tarfile.open(archive, "r:bz2") as tar:
            # The tarball holds a single top-level pyodide/ directory, which is
            # exactly the layout indexURL wants.
            tar.extractall(BUILD, filter="data")

    if not (BUILD / "pyodide" / "pyodide.js").exists():
        fail("the Pyodide tarball did not contain pyodide/pyodide.js")

    return "./pyodide/"


def main():
    parser = argparse.ArgumentParser(
        description="Assemble the acb web front end into site-build/.")
    parser.add_argument("--with-pyodide", action="store_true",
                        help="serve Pyodide from the site instead of a CDN")
    args = parser.parse_args()

    if not SITE.is_dir():
        fail(f"{SITE} not found -- run this from the repository root")

    wheel = build_wheel()

    print(f"Assembling {BUILD.name}/…")
    shutil.rmtree(BUILD, ignore_errors=True)
    shutil.copytree(SITE, BUILD)
    shutil.copy2(wheel, BUILD / wheel.name)

    examples = copy_examples()
    index_url = vendor_pyodide() if args.with_pyodide else PYODIDE_CDN

    # Everything the page needs to know that changes between builds, so that a
    # version bump means rebuilding rather than editing JavaScript.
    manifest = {
        "version": package_version(),
        "wheel": f"./{wheel.name}",
        "examples": examples,
        "pyodide": {"version": PYODIDE_VERSION, "indexURL": index_url},
    }
    (BUILD / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    total = sum(f.stat().st_size for f in BUILD.rglob("*") if f.is_file())
    print(f"\n{BUILD.name}/ ready -- {total / 1024 / 1024:.1f} MB, "
          f"builder {manifest['version']}, Pyodide from "
          f"{'the site' if args.with_pyodide else 'the CDN'}")
    print(f"\nTry it:  cd {BUILD.name} && {os.path.basename(sys.executable)} "
          f"-m http.server 8000")


if __name__ == "__main__":
    main()
