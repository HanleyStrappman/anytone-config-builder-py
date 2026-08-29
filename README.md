# Anytone Config Builder

Builds the `channels.csv`, `zones.csv`, `scanlists.csv` and `talkgroups.csv`
files that the Anytone CPS imports, from four readable CSV inputs you can keep
under version control.

Codeplug files are opaque: hard to diff, hard to audit, hard to prune, and easy
to get subtly wrong by hand. Keeping the *source* of your codeplug as CSV and
generating the rest means adding a repeater is one new row rather than an
afternoon of clicking.

This is a Python 3 port of [K7ABD's original Perl
tool](https://github.com/HanleyStrappman/anytone-config-builder). See
[Differences from the Perl original](#differences-from-the-perl-original) for
where the two diverge.

## Requirements

Python 3 and nothing else — no pip install, no virtualenv. (The Perl original
needed `Text::CSV_XS`.)

## Usage

The output directory must already exist; the builder will not create it.

```sh
mkdir -p output

./anytone_config_builder.py \
    --analog-csv=Analog__PNW-Community-260307.csv \
    --digital-others-csv=Digital-Others__PNW-Community-200926.csv \
    --digital-repeaters-csv=Digital-Repeaters__PNW-all-2026-08-29.csv \
    --talkgroups-csv=Talkgroups__PNW-all-2026-08-29.csv \
    --output-directory=output
```

Errors go to stderr and name the file and line they came from:

```
ERROR: Invalid Power Level: 'Massive' is not one of: Low, Mid, High, Turbo [On line #1 of Analog file.]
```

### Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--analog-csv` | *required* | Analog channels. |
| `--digital-others-csv` | *required* | One-off DMR channels. |
| `--digital-repeaters-csv` | *required* | The repeater × talkgroup matrix. |
| `--talkgroups-csv` | *required* | Talkgroup names and IDs. |
| `--output-directory` | *required* | Where the four output files are written. Must exist. |
| `--config` | `config` | Directory holding `channel-defaults.csv`. |
| `--sorting` | `alpha` | `alpha`, `repeaters-first`, or `analog-first`. |
| `--nicknames` | `off` | `off`, `prefix`, `suffix`, `prefix-forced`, `suffix-forced`. |
| `--hotspot-tx-permit` | `same-color-code` | `same-color-code` or `always`. |
| `--radio` | `uv878` | `uv878`, `uv878ii` or `uv890`. Which CPS layout to write. |

`--sorting` controls zone order: `alpha` sorts every zone by name, while
`repeaters-first` and `analog-first` put the repeater zones before or after the
analog and digital-other ones.

`--hotspot-tx-permit=always` sets TX Permit to `Always` on channels whose RX and
TX frequencies match, which is what a hotspot wants.

### Radios

CPS versions disagree about the shape of the import files, so pick the one
matching your radio with `--radio`. The file names are the same whichever you
choose; only the contents differ.

| | `uv878` | `uv878ii` | `uv890` |
| --- | --- | --- | --- |
| `channels.csv` columns | 51 | 55 | 77 |
| `zones.csv` columns | 11 | 12 | 12 |
| `talkgroups.csv` columns | 7 | 5 | 5 |
| `scanlists.csv` columns | 18 | 18 | 18 |
| Frequencies | as written in the input | five decimals | five decimals |

**`uv878` is the layout the Perl original wrote**, kept for older CPS versions.
If you have an AT-D878UVII, you want `uv878ii`: its channel row differs from the
old one from column 11 onward, so importing `uv878` output into it would land
every field in the wrong column.

`uv878ii` and `uv890` share a layout; the UV890 simply continues past column 55
with a tail of NXDN and miscellaneous settings, and splits the TX color code into
its own `txcc` column (always the same value as the RX one). Both add a trailing
`Zone Hide` to zones and drop `Country` and `Remarks` from talkgroups.

Each radio has its own defaults file in the `--config` directory —
`channel-defaults.csv`, `uv878ii-channel-defaults.csv`,
`uv890-channel-defaults.csv` — giving the value for every CPS field the inputs
do not mention.

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

## Input files

Plain ASCII CSV, editable in any spreadsheet. The four files in the repo root
are a working PNW set you can copy and adapt.

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

## Output

Four files, ready to import:

- `channels.csv` — one channel per row in the analog and digital-others files,
  plus one per repeater/talkgroup pair from the matrix
- `zones.csv` — one zone per zone named in the analog and digital-others files,
  plus one per repeater
- `scanlists.csv` — one per zone from the analog and digital-others files, and
  one per *talkgroup* from the repeaters file, so hitting scan while listening
  to a talkgroup sweeps that talkgroup across every repeater carrying it
- `talkgroups.csv` — the talkgroup list

The CPS caps a scanlist at 50 channels and a zone at 250. Anything longer is
truncated with a warning on stdout.

The `--config` directory supplies the value for every CPS field the inputs don't
mention, in a file per radio. Edit it to change defaults across all generated
channels.

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
- **`--radio` is new.** The Perl only ever wrote the one layout, which survives
  as `uv878`.
- **Scanlist rows fill all 18 columns.** The Perl emitted only 12 values under
  its own 18-column header, so everything from `Priority Channel 1` onward sat
  one column to the left and `Dwell Time[s]` was missing entirely. The values now
  written are the ones UV878 and UV890 exports both contain, identically on every
  scanlist.

Argument handling deliberately keeps `Getopt::Long`'s habits: an unknown option
warns on stderr and prints usage, stray non-option arguments are ignored, `--`
ends option parsing, and unique option prefixes such as `--sort` are accepted.

## Known issues

- **CTCSS tones are passed through as written.** An input of `123` stays `123`,
  where a radio's own export says `123.0`. Harmless if your CPS is relaxed about
  it; normalise the input file if it is not.
- **Talkgroup IDs are not trimmed.** A stray space in the talkgroups CSV
  (`Simplex 99, 99`) reaches the output as ` 99`.
- **Analog channels carry digital defaults.** They get `Busy Lock/TX Permit` from
  the defaults file where a radio would write `Off`, and their `Contact` is left
  blank where the CPS back-fills a placeholder talkgroup. Harmless — the CPS
  normalises both on import — but it is why generated and exported files differ
  on analog rows.

## Tests

```sh
python3 tests/test_output_regression.py
python3 tests/test_error_regression.py
python3 tests/test_args_regression.py
```

Golden-file regression tests covering the generated files for all three radios
across all 30 combinations of `--sorting`, `--nicknames` and
`--hotspot-tx-permit`, 35 malformed-input cases, and 20 command-line cases. They need nothing installed
and run from any directory. See [tests/README.md](tests/README.md) for how to
re-record them after an intentional change.

## License

GPL-3. Copyright (C) 2020 Andrew B Dickinson (K7ABD) for the original tool,
Copyright (C) 2026 Scott Robinson (AG7T) for the Python port and test suite.
See [LICENSE.md](LICENSE.md).
