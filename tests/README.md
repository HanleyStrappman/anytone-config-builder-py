# Regression tests

Golden-file tests for `anytone_config_builder.py`. Each one runs the builder and
compares its exit status, its messages, and the files it generates against
recorded results under `golden/`.

Run them with plain `python3`; there is nothing to install, and they work from
any working directory.

```
python3 tests/test_output_regression.py
python3 tests/test_error_regression.py
python3 tests/test_args_regression.py
```

| Script | What it covers |
| --- | --- |
| `test_output_regression.py` | The four generated CSVs on the real PNW inputs, across all 30 combinations of `--sorting`, `--nicknames` and `--hotspot-tx-permit`. |
| `test_error_regression.py` | 35 malformed-input cases — bad headers, out-of-range and non-member field values, over-long names, unknown talkgroups, missing files. |
| `test_args_regression.py` | Command-line handling: unknown options, stray positionals, `--`, option abbreviation, missing required arguments. |

## Re-recording

When you change the builder on purpose, the goldens will no longer match. Re-record
with `--update` and **read the diff** — that diff is the whole point of these tests,
and it is the only thing standing between an intended change and an accidental one.

```
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
  for each of the 30 flag combinations.
- `golden/default/` — full copies of the four CSVs for the default combination
  (`alpha` / `off` / `same-color-code`), so a digest mismatch can be turned into a
  readable diff instead of two hex strings. The other 29 are compared by digest
  only; keeping them all in full would cost about 28MB of near-identical CSVs.
- `golden/errors.json`, `golden/args.json` — exit status and messages per case.
- `fixtures/` — the smallest input set that still exercises all three readers,
  used as the starting point the error cases mutate.
- `_golden.py` — shared plumbing: running the builder, scrubbing machine-specific
  paths out of its output, loading and saving goldens, reporting differences.

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

- **Getopt::Long's argument habits are reproduced deliberately**: an unknown
  option warns `Unknown option: <name>` on stderr and then prints usage; stray
  non-option arguments are ignored; `--` ends option parsing; and unique prefixes
  of an option name are accepted.
