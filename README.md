# Anytone Config Builder

Builds the four channel, zone, scanlist and talkgroup files that the Anytone CPS
imports, from four readable CSV inputs you can keep under version control.

Codeplug files are opaque: hard to diff, hard to audit, hard to prune, and easy
to get subtly wrong by hand. Keeping the *source* of your codeplug as CSV and
generating the rest means adding a repeater is one new row rather than an
afternoon of clicking.

This is a Python 3 port of [K7ABD's original Perl
tool](https://github.com/HanleyStrappman/anytone-config-builder). See
[Differences from the Perl original](#differences-from-the-perl-original) for
where the two diverge.

AG7T did use [claude-code](https://claude.com/product/claude-code)
to help analyze the various CPS formats and write the code.
This was done under direct guidance of AG7T who takes
full responsibility for the code. AG7T finds test cases written by
claude-code to be outstanding and that produces a level of quality that
exceeds many hobby projects like this one.

## Requirements

Python 3 and nothing else — no third-party packages at any version. (The Perl
original needed `Text::CSV_XS`.)

## Install

Optional: a checkout runs without installing anything.

```sh
pip install .                    # from a checkout
pip install dist/anytone_config_builder-*.whl
```

Either puts `anytone-config-builder` (and the shorter alias `acb`) on your PATH,
and carries the channel-defaults files along with it, so an installed copy needs
no `--config` and works from any directory. There is also a
[website](#website) that runs the builder in the browser and needs no install
at all.

To build the distribution yourself:

```sh
python -m build          # writes dist/*.whl and dist/*.tar.gz
```

The version is `__version__` in `anytone_config_builder/__init__.py`, and
nothing else reads it from anywhere else.
[bump-my-version](https://github.com/callowayproject/bump-my-version) moves it
there and in `pyproject.toml`, then commits and tags `v<version>`:

```sh
uvx bump-my-version show-bump     # what each bump would produce
uvx bump-my-version bump patch    # or minor, or major
```

It refuses to run on a dirty tree, so commit your work first. It is a
release-time tool only; the package itself still installs nothing.

## Usage

The output directory must already exist; the builder will not create it.

Installed, the command is `acb`. From a checkout it is
`python -m anytone_config_builder`, or `anytone_config_builder/builder.py`
directly — the three take identical arguments, and the rest of this README
writes `acb`.

```shell
mkdir -p output

acb \
    --analog-csv=Analog__PNW-Community-260307.csv \
    --digital-others-csv=Digital-Others__PNW-Community-200926.csv \
    --digital-repeaters-csv=Digital-Repeaters__PNW-all-2026-08-29.csv \
    --talkgroups-csv=Talkgroups__PNW-all-2026-08-29.csv \
    --output-directory=output
```

Errors go to stderr and name the file and line they came from:

```text
ERROR: Invalid Power Level: 'Massive' is not one of: Low, Mid, High, Turbo [On line #1 of Analog file.]
```

### Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--analog-csv` | *required* | Analog channels. |
| `--digital-others-csv` | *required* | One-off DMR channels. |
| `--digital-repeaters-csv` | *required* | The repeater × talkgroup matrix. |
| `--talkgroups-csv` | *required* | Talkgroup names and IDs. |
| `--am-air-csv` | *optional* | AM airband channels. Only format `3` reads the result. |
| `--output-directory` | *required* | Where the output files are written. Must exist. |
| `--config` | *packaged* | Directory holding the channel defaults files. Defaults to the copy inside the package. |
| `--sorting` | `alpha` | `alpha`, `repeaters-first`, or `analog-first`. |
| `--nicknames` | `prefix` | `off`, `prefix`, `suffix`, `prefix-forced`, `suffix-forced`. |
| `--hotspot-tx-permit` | `same-color-code` | `same-color-code` or `always`. |
| `--cps-format` | `1` | `0`, `1`, `2` or `3`. Which CPS layout to write. |

`--sorting` controls zone order: `alpha` sorts every zone by name, while
`repeaters-first` and `analog-first` put the repeater zones before or after the
analog and digital-other ones.

`--hotspot-tx-permit=always` sets TX Permit to `Always` on channels whose RX and
TX frequencies match, which is what a hotspot wants.

### CPS formats

CPS versions disagree about the shape of the import files, and which shape yours
wants is a property of the CPS rather than of the radio — a newer CPS for the
same radio can read a different layout. So the layouts are numbered, and
`--cps-format` picks one. Formats `0` to `2` agree on the file names and differ
only in contents; format `3` writes the names AT-D890UV CPS 1.05 uses.

| | `0` | `1` | `2` | `3` |
| --- | --- | --- | --- | --- |
| Verified against | AT-D868UV CPS | the Perl original | AT-D878UVII, and AT-D878UV on later firmware | AT-D890UV CPS 1.05 |
| Channel file | `channels.csv`, 38 columns | `channels.csv`, 51 | `channels.csv`, 55 | `Channel.CSV`, 77 |
| Zone file | `zones.csv`, 5 columns | `zones.csv`, 11 | `zones.csv`, 12 | `DMRZones.CSV`, 12 |
| Talkgroup file | `talkgroups.csv`, 5 columns | `talkgroups.csv`, 7 | `talkgroups.csv`, 5 | `DMRTalkGroups.CSV`, 5 |
| Scanlist file | `scanlists.csv`, 12 columns | `scanlists.csv`, 18 | `scanlists.csv`, 18 | `ScanList.CSV`, 18 |
| Frequencies | five decimals | as written in the input | five decimals | five decimals |
| Airband | not read | not read | not read | `AMAir.CSV`, `AMZone.CSV` |

The numbers run oldest CPS to newest, and each is a fixed identifier — a format
discovered later is appended rather than slotted in. **Format `1` is the default
because it is the layout the Perl original wrote**, so a command line that names
no format keeps producing what it always has.

Format `0` is the narrowest: its channel row is format `1`'s first 38 columns
(with `Scan List` named `CH Scan List`), its zones and scanlists carry no RX/TX
frequency column beside each channel they name, and its talkgroups have no
`Country` or `Remarks`.

Format `2` differs from `1` in the channel row from column 11 onward, so
importing `1` output into a CPS that wants `2` would land every field in the
wrong column. Formats `2` and `3` share a layout; `3` simply continues past
column 55 with a tail of NXDN and miscellaneous settings, and splits the TX
color code into its own `txcc` column (always the same value as the RX one).
Both add a trailing `Zone Hide` to zones and drop `Country` and `Remarks` from
talkgroups.

Format `3` is also the only one whose file names differ, because CPS 1.05 handles
the AM airband alongside DMR and keeps the two apart by name: the DMR zones and
talkgroups take the prefix, leaving `AMZone.CSV` and `AMAir.CSV` for the airband.
Those two are written only when `--am-air-csv` gives them something to hold —
without it neither file appears and the CPS keeps whatever airband channels the
radio already has.

Any format will write the airband pair if asked, since the pair has only one
shape; passing `--am-air-csv` to formats `0` to `2` warns that the CPS those
target will not read them, but still builds everything.

One AT-D878UV shows why this is a CPS property and not a radio one: exported
from two CPS versions, its channel file came out 52 columns wide from the older
and 55 from the newer, while its zones, scanlists and talkgroups were identical
either way. The 55-column one is format `2`. The 52-column layout is a strict
prefix of it and is **not** a format this tool writes — update the radio's
firmware and it becomes a format `2` radio.

If an import is rejected or lands values in the wrong fields, try another
format rather than assuming your radio's name picks it — export a codeplug from
your own CPS and compare its headers against the four generated files.

Each format has its own defaults file in the `--config` directory —
`channel-defaults-0.csv` through `channel-defaults-3.csv` — giving the value for
every CPS field the inputs do not mention.

### Nicknames

Append `;NICK` to a zone name in the repeaters file and the nickname can be
worked into each channel name, which helps when every repeater's channels are
otherwise named identically after their talkgroups. With `Ariel/Ariel VHF;ARA`
as the zone name, the zone is still called `Ariel/Ariel VHF` and its channels
come out as:

| `--nicknames=off` | `--nicknames=prefix` | `--nicknames=suffix` |
| --- | --- | --- |
| `Audio Test 2` | `ARA Audio Test 2` | `Audio Test 2 ARA` |
| `BC 1` | `ARA BC 1` | `BC 1 ARA` |
| `California 1` | `ARA California 1` | `California 1 ARA` |

Talkgroup names take a `;nick` suffix too, used when the full name plus the zone
nickname will not fit in 16 characters. The `-forced` modes always use the short
form even when the long one would fit.

`prefix` is the default: with `off`, every repeater in the matrix produces a
channel named after nothing but its talkgroup, so the thousands of channels
collapse onto a hundred-odd names and the CPS has no way to tell them apart.

## Input files

Plain ASCII CSV, editable in any spreadsheet. The files in the repo root are a
working PNW set you can copy and adapt.

### Analog

`Zone, Channel Name, Bandwidth, Power, RX Freq, TX Freq, CTCSS Decode, CTCSS Encode, TX Prohibit`

- **Zone**, **Channel Name** — up to 16 characters
- **Bandwidth** — `25K` for FM, `12.5K` for NFM
- **Power** — `Turbo`, `High`, `Mid`, `Low`
- **RX/TX Freq** — MHz
- **CTCSS Decode/Encode** — tone in Hz, a DCS code such as `D023N`, or `Off`
- **TX Prohibit** — `On` or `Off`. Useful for receive-only entries such as NWS
  weather channels

### Digital-Others

One-off DMR channels — simplex, hotspots, digital APRS.

`Zone, Channel Name, Power, RX Freq, TX Freq, Color Code, Talk Group, TimeSlot, Call Type, TX Permit`

- **Talk Group** — must match a name in the talkgroups file
- **TimeSlot** — `1` or `2`
- **Call Type** — `Group Call` or `Private Call`
- **TX Permit** — `Always`, `ChannelFree`, `Same Color Code`, `Different Color Code`

### Digital-Repeaters

Where most of the work happens. The first six columns describe the repeater:

`Zone Name, Comment, Power, RX Freq, TX Freq, Color Code`

**Comment** is for your own notes and is ignored. Every remaining column is
headed with a talkgroup name, and each cell holds the timeslot that talkgroup
uses on that repeater — `1`, `2`, or `-` if it isn't carried. Append `P` (for
example `1P`) for a private call.

That matrix is multiplied out into one channel per repeater per talkgroup, so
adding a repeater means adding one row.

### Talkgroups

Two columns, no header: the talkgroup name and its numeric ID. Names must match
the ones used in the two DMR files above.

### Airband

`Zone, Channel Name, Frequency`

Optional, and passed with `--am-air-csv`. `Airband__PNW.csv` in the repo root is
a starting point to fill in.

- **Zone**, **Channel Name** — up to 16 characters
- **Frequency** — MHz, written out to four decimals

One row per channel *per zone*. Unlike the analog file, a channel name repeated
across zones is **one** airband channel with two memberships, not two channels —
the radio keeps a single flat airband table that the zones then name. The same
name at two different frequencies is an error, since one table entry cannot be
both.

## Output

Four files, ready to import — plus two more when `--am-air-csv` is given. The
names below are what formats `0` to `2` write; format `3` writes the same four as
`Channel.CSV`, `DMRZones.CSV`, `ScanList.CSV` and `DMRTalkGroups.CSV`.

- `channels.csv` — one channel per row in the analog and digital-others files,
  plus one per repeater/talkgroup pair from the matrix
- `zones.csv` — one zone per zone named in the analog and digital-others files,
  plus one per repeater
- `scanlists.csv` — one per zone from the analog and digital-others files, and
  one per *talkgroup* from the repeaters file, so hitting scan while listening
  to a talkgroup sweeps that talkgroup across every repeater carrying it
- `talkgroups.csv` — the talkgroup list
- `AMAir.CSV`, `AMZone.CSV` — the airband channel table and the zones over it,
  only when `--am-air-csv` is given. Same name whichever format is chosen.

The CPS caps a scanlist at 50 channels and a zone at 250. Anything longer is
truncated with a warning on stdout.

The `--config` directory supplies the value for every CPS field the inputs don't
mention, in a file per CPS format. It defaults to `anytone_config_builder/config`
inside the package, wherever that package happens to live. To change defaults
across all generated channels, either edit the packaged files in a checkout or
copy the directory somewhere and point `--config` at it.

## Before importing into the CPS

- **Duplicate names.** Repeater channels are named after their talkgroups, so
  the same name recurs across repeaters. Enable *Tools > Mode >* "Contact name
  is not unique / Channel name is not unique" first, or the import will fail.
- **Radio ID.** The output references a radio ID named `DMR ID`. Under the
  *Digital* tab, add your DMR ID to the Radio ID List under that name.
- **Contacts.** Not generated. Start from a codeplug that has them, then import
  these files over the top.

## Differences from the Perl original

- **Over-long names are truncated, not fatal.** Zone names, channel names and
  contacts longer than 16 characters are reported as `Invalid <thing>:
  '<original>' is more than 16 characters, truncated to '<what it kept>'` and
  the build continues. The Perl stopped instead, which meant one long name in a
  community input file cost you the whole run.

  The talkgroup table is keyed on the same shortened name, so a channel pointing
  at an over-long talkgroup still resolves. Two talkgroups sharing their first
  16 characters collapse into one entry the radio cannot tell apart, and warn.

  A run that truncates still exits **0** — check stderr, not the exit status, if
  you need to know whether anything was cut.
- **Errors go to stderr**, warnings to stdout. The Perl printed both to stdout.
- **A blank line mid-file is skipped** rather than parsed as a row, because
  Python's `csv` yields `[]` where Perl's `Text::CSV` yields a one-element row.
- **`--cps-format` is new.** The Perl only ever wrote the one layout, which
  survives as format `1`, the default.
- **`--nicknames` defaults to `prefix`**, where the Perl defaulted to `off`. On
  a repeater matrix of any size `off` names every channel after its talkgroup
  alone, so a run with no flags produced thousands of channels sharing a hundred
  names — files the CPS accepts but the radio cannot be used with. Pass
  `--nicknames=off` for the Perl's behaviour.
- **Scanlist rows fill all 18 columns.** The Perl emitted only 12 values under
  its own 18-column header, so everything from `Priority Channel 1` onward sat
  one column to the left and `Dwell Time[s]` was missing entirely. The values now
  written are the ones AT-D878UV and AT-D890UV exports both contain, identically
  on every scanlist.

Argument handling deliberately keeps `Getopt::Long`'s habits: an unknown option
warns on stderr and prints usage, stray non-option arguments are ignored, `--`
ends option parsing, and unique option prefixes such as `--sort` are accepted.

## Known issues

- **CTCSS tones are passed through as written.** An input of `123` stays `123`,
  where a radio's own export says `123.0`. Harmless if your CPS is relaxed about
  it; normalise the input file if it is not.
- **Zones are written with `Zone Hide` off.** Formats `2` and `3` end each zone
  row with `0`, where a radio's own export writes `1` on every zone. The CPS
  accepts `0` — it is what the AT-D890UV CPS 1.05 imported — and appears to
  normalise the column on export.
- **Analog channels carry digital defaults.** They get `Busy Lock/TX Permit` from
  the defaults file where a radio would write `Off`, and their `Contact` is left
  blank where the CPS back-fills a placeholder talkgroup. Harmless — the CPS
  normalises both on import — but it is why generated and exported files differ
  on analog rows.

## Website

The same builder runs in a browser, for people who would rather not install
Python at all. `site/` holds the page and `build_site.py` assembles it:

```sh
python3 build_site.py
cd site-build && python3 -m http.server 8000
```

`site-build/` is the whole site — static files, nothing to run on the server.
The builder is stdlib-only and therefore runs unmodified under
[Pyodide](https://pyodide.org), so the visitor's CSVs are never uploaded; there
is no server to upload them to. The page calls the same `cli()` the `acb`
command does, over the same packaged channel-defaults files, so its output is
byte-for-byte what the command line would have written.

The wheel is rebuilt on every run and the page reads its version from
`manifest.json`, so a `bump-my-version` bump reaches the site by rebuilding it
rather than by editing anything.

Pyodide comes from a CDN by default. To serve it yourself as well — for a host
with no outbound access, or just to depend on nothing:

```sh
python3 build_site.py --with-pyodide
```

That fetches the 6MB Pyodide core build, taking `site-build/` to about 13MB.
Only the core is needed: the builder is unpacked straight onto `sys.path`
rather than installed with `micropip`, so none of Pyodide's bundled packages
are wanted.

### Deploying

Every path in the page is relative, so the site works at a domain root, in a
subdirectory, or under the `/<repo>/` path GitHub Pages serves a project from —
without rebuilding.

```sh
rsync -a --delete site-build/ user@host:/var/www/acb/
```

An nginx server block. The `.wasm` type is the part that bites: nginx's stock
`mime.types` had no entry for it before 1.21, and the wrong type stops
WebAssembly instantiating — which only matters if you passed `--with-pyodide`.

```nginx
server {
    listen 443 ssl;
    server_name acb.example.org;
    root /var/www/acb;

    types { application/wasm wasm; }

    gzip on;
    gzip_types text/css application/javascript application/json text/csv
               text/x-python application/wasm;

    location / { try_files $uri $uri/ =404; }

    # The wheel carries its version in the filename, so it can cache forever;
    # index.html must not, or a rebuild goes unnoticed.
    location ~ \.whl$ {
        add_header Cache-Control "public, max-age=31536000, immutable";
    }
    location = /index.html {
        add_header Cache-Control "no-cache";
    }
}
```

## Tests

```sh
python3 tests/test_output_regression.py
python3 tests/test_error_regression.py
python3 tests/test_args_regression.py
python3 tests/test_web_equivalence.py
```

Golden-file regression tests covering the generated files for all four CPS
formats across all 30 combinations of `--sorting`, `--nicknames` and
`--hotspot-tx-permit`, 35 malformed-input cases, and 21 command-line cases. They need nothing installed
and run from any directory. See [tests/README.md](tests/README.md) for how to
re-record them after an intentional change.

The fourth is not a golden-file test: it runs the [website](#website)'s builder
and the command line over the same inputs and asserts they cannot be told apart,
which is the promise the website makes to someone who cannot check it themselves.

## License

GPL-3. Copyright (C) 2020 Andrew B Dickinson (K7ABD) for the original tool,
Copyright (C) 2026 Scott Robinson (AG7T) for the Python port and test suite.
See [LICENSE.md](LICENSE.md).
