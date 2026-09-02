# Regression tests

Golden-file tests for `anytone_config_builder/builder.py`. Each one runs the builder and
compares its exit status, its messages, and the files it generates against
recorded results under `golden/`. `test_web_equivalence.py` is the exception and
needs no goldens; see below.

Run them with plain `python3`; there is nothing to install, and they work from
any working directory.

```text
python3 tests/test_output_regression.py
python3 tests/test_error_regression.py
python3 tests/test_args_regression.py
python3 tests/test_web_equivalence.py
```

| Script | What it covers |
| --- | --- |
| `test_output_regression.py` | The four generated CSVs on the real PNW inputs, for all four CPS formats across all 30 combinations of `--sorting`, `--nicknames` and `--hotspot-tx-permit`. |
| `test_error_regression.py` | 55 malformed-input cases — bad headers, out-of-range and non-member field values, over-long names, unknown talkgroups, missing files, short rows, oversized fields and files, and each radio table limit both over and exactly at the line. |
| `test_args_regression.py` | Command-line handling: unknown options, stray positionals, `--`, option abbreviation, `--cps-format`, missing required arguments. |
| `test_web_equivalence.py` | That `site/acb_web.py` builds exactly what the command line builds, across the formats and flags, plus the things only the web path can get wrong: CRLF survival, a stripped BOM, a deterministic zip, no stale files between builds, and a fatal error reaching the page intact. |

## Re-recording

When you change the builder on purpose, the goldens will no longer match. Re-record
with `--update` and **read the diff** — that diff is the whole point of these tests,
and it is the only thing standing between an intended change and an accidental one.

```text
python3 tests/test_output_regression.py --update
```

## Where the goldens came from

These started life as differential tests against the Perl original,
`anytone-config-builder.pl`. The recorded results were captured from a build
verified byte-identical to that original across all 30 flag combinations, with
matching messages and exit statuses on every error and command-line case, so they
carry that verification forward. The Perl script has since been removed, along
with the `Text::CSV_XS` shim that let it run here.

## Layout

- `golden/outputs.json` — exit status, messages and a SHA-256 per generated file,
  for each CPS format crossed with each of the 30 flag combinations. The file
  names are recorded, not assumed, so a format that renames its outputs shows up
  as a diff rather than as four files quietly going missing.
- `golden/default/<format>/` — full copies of the four CSVs for each format's
  default combination (`alpha` / `prefix` / `same-color-code`), so a
  digest mismatch can be turned into a readable diff instead of two hex strings.
  The rest are compared by digest only; keeping them all in full would cost tens
  of MB of near-identical CSVs.
- `golden/errors.json`, `golden/args.json` — exit status and messages per case.
- `fixtures/` — the smallest input set that still exercises every reader, used as
  the starting point the error cases mutate. `airband.csv` is deliberately not
  wired into the 30-combination cross product: airband is an optional fifth input
  with its own per-format cases, so those 120 goldens keep meaning exactly what
  they meant before it existed.
- `_golden.py` — shared plumbing: running the builder, scrubbing machine-specific
  paths out of its output, loading and saving goldens, reporting differences.
- `test_web_equivalence.py` — no goldens of its own. The command line is the
  oracle: every case runs both it and `site/acb_web.py` over the same files and
  compares. So there is nothing to re-record, and nothing that can be re-recorded
  wrong — but it does mean the test says only that the two agree, not that either
  is right. What makes them right is the goldens above.

The real CSVs in the repo root are only ever read. The error cases mutate copies
in a temporary directory, and every run writes its output to a temporary directory
that is removed afterwards.

## Behaviour these tests pin down

- **Over-long strings are truncated, not fatal.** Zone names, channel names and
  contacts longer than 16 characters are reported as
  `Invalid <thing>: '<original>' is more than 16 characters, truncated to
  '<what it kept>'`, and the build continues with the shortened value. The Perl
  original stopped instead.

  The talkgroup table is keyed on that same shortened name, so a channel pointing
  at an over-long talkgroup still resolves rather than becoming `Talkgroup '...'
  is referenced but not defined`. If two talkgroup names share their first 16
  characters they collapse into one entry the radio cannot tell apart; that gets
  its own `WARNING`, and the last definition wins.

  A run that truncates still exits **0**. Check stderr, not just the exit status,
  if you care whether anything was cut.

- **Errors go to stderr**, warnings to stdout. The Perl printed both to stdout.

- **`--cps-format` selects the CPS layout**, under the same four file names in
  every case. Format `1` is what the Perl wrote and is the default; `2` (55
  channel columns) and `3` (77) add a trailing `Zone Hide`, drop `Country` and
  `Remarks` from talkgroups, and pad frequencies to five decimals. Format `0` is
  narrower than all of them: 38 channel columns, and no RX/TX frequency columns
  beside the channels named in zones and scanlists. Every non-default format's
  goldens were checked against a real CPS export: all four headers match, and
  every mapped column carries the same value as the verified format `1` build.
  Format `3` has since been imported successfully by the AT-D890UV CPS 1.05.

- **Scanlist rows fill the whole header.** The Perl emitted 12 values under an
  18-column header, misaligning everything from `Priority Channel 1` and dropping
  `Dwell Time[s]`. Formats `1`–`3` get the missing six. Their values are
  confirmed, not inferred: every one of the 53 scanlists in a real AT-D878UV
  export carries `Off,Off,Off,"","",Off,"","",Selected,0.5,0.1,0.1,0.0`, which is
  `SCANLIST_DETAILS` byte for byte, blank priority-channel frequency fields
  included. Format `0`'s scanlist header really is 12 columns wide, so it takes
  the same values without those four blanks.

- **Getopt::Long's argument habits are reproduced deliberately**: an unknown
  option warns `Unknown option: <name>` on stderr and then prints usage; stray
  non-option arguments are ignored; `--` ends option parsing; and unique prefixes
  of an option name are accepted.
