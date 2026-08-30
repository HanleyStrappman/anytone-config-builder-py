#!/usr/bin/env python3
#
# Anytone config builder -- helps create codeplugs for Anytone (and similar)
# DMR radios.
#
# Copyright (C) 2020 Andrew B Dickinson (K7ABD)
# Copyright (C) 2026 Scott Robinson (AG7T)
#
# This file is a Python port of anytone-config-builder.pl, made in 2026.
# Upstream: https://github.com/HanleyStrappman/anytone-config-builder
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
"""Anytone config builder.

A Python port of anytone-config-builder.pl.

Reads the analog, digital-other and digital-repeater channel CSVs (plus a
talkgroup CSV and a channel-defaults config file) and writes the four channel,
zone, scanlist and talkgroup files that the Anytone CPS software imports.  What
those four are called depends on the CPS -- see OUTPUT_FILES.

An optional airband CSV adds the AM_FILES pair on top, for the one CPS that
reads them.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from functools import cmp_to_key

# There are other fields, but these are the ones we care about
CHAN_NUM = 0
CHAN_NAME = 1
CHAN_RX_FREQ = 2
CHAN_TX_FREQ = 3
CHAN_MODE = 4
CHAN_POWER = 5
CHAN_BANDWIDTH = 6
CHAN_CTCSS_DEC = 7
CHAN_CTCSS_ENC = 8
CHAN_CONTACT = 9
CHAN_CALL_TYPE_OLD = 10
CHAN_CALL_TYPE_NEW = 44
CHAN_TG_ID = 45
CHAN_TX_PERMIT = 12
CHAN_SQUELCH_MODE = 13
CHAN_COLOR_CODE = 19
CHAN_TIME_SLOT = 20
CHAN_SCANLIST_NAME = 21
CHAN_TX_PROHIBIT = 23
CHAN_DMR_MODE = 47
CHAN_PTT_PROHIBIT = 48
ACB_ZONE_NICKNAME = 1000

VAL_DIGITAL = "D-Digital"
VAL_ANALOG = "A-Analog"
VAL_NO_TIME_SLOT = "-"  # this is from the input CSV, not a Anytone-ism
VAL_TX_PERMIT_FREE = "ChannelFree"
VAL_TX_PERMIT_SAME = "Same Color Code"
VAL_TX_PERMIT_ALWAYS = "Always"
VAL_CALL_TYPE_GROUP = "Group Call"
VAL_CALL_TYPE_PRIVATE = "Private Call"
VAL_CTCSS_DCS = "CTCSS/DCS"
VAL_DMR_MODE_SIMPLEX = 0
VAL_DMR_MODE_REPEATER = 1
LENGTH_CHAN_NAME = 16


################################################################################
##########   CPS FORMATS
################################################################################

# Which shape the import files have to be is a property of the CPS, not of the
# radio: a newer CPS for the same radio reads a different layout.  So the layouts
# are numbered rather than named after hardware, and --cps-format picks one:
#
#   0  the 38-column channel layout (AT-D868UV CPS)
#   1  the original layout, as the Perl wrote it (AT-D878UV CPS)
#   2  the 55-column channel layout (AT-D878UVII CPS)
#   3  the 77-column channel layout (AT-D890UV CPS 1.05)
#
# They run oldest CPS to newest, and each number is a fixed identifier: a format
# discovered later is appended rather than slotted in.  Format 1 is the default,
# because it is the layout the Perl original wrote.
#
# Channels are assembled internally in the format 1 column layout -- the CHAN_*
# constants above are indices into that layout.  A format describes how to turn
# that into one CPS's import files: what to call them, which column each internal
# field lands in, and the handful of places the other three files differ.


# The fixed tail of a scanlist row, from Scan Mode onwards.  Taken from AT-D878UV
# and AT-D890UV exports, which agree and use the same values on every scanlist
# they contain.  The Perl original pushed only twelve values under an 18-column
# header, leaving the row a field short and shifting everything from Priority
# Channel 1 leftwards.
SCANLIST_DETAILS = ("Off", "Off", "Off", "", "", "Off", "", "", "Selected",
                    "0.5", "0.1", "0.1", "0.0")

# The same tail without the priority channels' RX and TX frequency columns, for
# formats whose scanlist file does not carry them.
SCANLIST_DETAILS_NO_FREQS = ("Off", "Off", "Off", "Off", "Selected",
                             "0.5", "0.1", "0.1", "0.0")

# The four file names formats 0 through 2 share.  Each is what its own CPS writes
# when it exports, which is also what it expects back on import.
OUTPUT_FILES = {"channels": "channels.csv", "zones": "zones.csv",
                "scanlists": "scanlists.csv", "talkgroups": "talkgroups.csv"}

# AT-D890UV CPS 1.05 handles the AM airband as well as DMR, and keeps the two
# apart by name: its DMR zones and talkgroups take the prefix, leaving AMZone.CSV
# and AMAir.CSV for the airband -- see AM_FILES.
FORMAT_3_FILES = {"channels": "Channel.CSV", "zones": "DMRZones.CSV",
                  "scanlists": "ScanList.CSV", "talkgroups": "DMRTalkGroups.CSV"}

# The airband pair, written only when --am-air-csv supplies something to put in
# them.  Unlike the four above these have no per-format variants, because only
# one CPS reads them at all -- so they are a constant rather than a format field.
AM_FILES = {"am_air": "AMAir.CSV", "am_zones": "AMZone.CSV"}

# The airband channel table is a flat list the zones then name.  Its frequencies
# carry four decimals, where the DMR side of the same CPS uses five.
AM_FREQ_DECIMALS = 4
LENGTH_AM_NAME = 16


class CpsFormat:
    """How one CPS wants its four import files shaped."""

    def __init__(self, name, defaults, columns=None, freq_decimals=None,
                 zone_hide=False, talkgroup_notes=True, member_freqs=True,
                 files=None, airband=False):
        self.name = name
        self.defaults = defaults            # channel defaults file, inside --config
        self.columns = columns              # output column -> internal CHAN_* field
        self.freq_decimals = freq_decimals  # None to pass frequencies through as-is
        self.zone_hide = zone_hide          # trailing "Zone Hide " column
        self.talkgroup_notes = talkgroup_notes  # Country and Remarks columns
        self.member_freqs = member_freqs    # RX/TX frequency columns beside each
                                            # channel named in zones and scanlists
        self.files = files or OUTPUT_FILES  # what this CPS calls the four outputs
        self.airband = airband              # whether this CPS reads AM_FILES at all;
                                            # gates the warning, not the writing

    def field_for_column(self, column):
        """Which internal field feeds this output column, or None for a default.

        A format with no explicit map works in the layout the builder already
        uses, so each column is fed by the identically numbered field.
        """
        if self.columns is None:
            return column
        return self.columns.get(column)

    def freq(self, value):
        """Render a frequency the way this CPS writes them."""
        if self.freq_decimals is None:
            return value
        return f"{float(value):.{self.freq_decimals}f}"


# Format 3 keeps format 1's first nine columns, then inserts a talkgroup ID column
# which shifts the rest along by one, and carries the DMR mode and PTT prohibit
# fields inline rather than appended at the end.  It also writes the TX color code
# ("txcc") as a separate column from the RX one, always with the same value.
FORMAT_3_COLUMNS = {
    0: CHAN_NUM,
    1: CHAN_NAME,
    2: CHAN_RX_FREQ,
    3: CHAN_TX_FREQ,
    4: CHAN_MODE,
    5: CHAN_POWER,
    6: CHAN_BANDWIDTH,
    7: CHAN_CTCSS_DEC,
    8: CHAN_CTCSS_ENC,
    9: CHAN_CONTACT,
    10: CHAN_CALL_TYPE_OLD,
    11: CHAN_TG_ID,
    13: CHAN_TX_PERMIT,
    14: CHAN_SQUELCH_MODE,
    20: CHAN_COLOR_CODE,
    21: CHAN_TIME_SLOT,
    22: CHAN_SCANLIST_NAME,
    24: CHAN_TX_PROHIBIT,
    45: CHAN_DMR_MODE,
    76: CHAN_COLOR_CODE,
}

# Format 2 stops at 55 columns -- format 3 without its NXDN tail, and without the
# separate TX color code that lives beyond it.
FORMAT_2_COLUMNS = {column: field for column, field in FORMAT_3_COLUMNS.items()
                    if column < 55}

# Format 0's channel row is format 1's first 38 columns, so it needs no map of its
# own -- only a defaults file that stops there.  Its other three files are the
# narrow ones: no frequency columns beside the channels named in zones and
# scanlists, and no Country or Remarks on talkgroups.
CPS_FORMATS = {
    "0": CpsFormat(
        name="0",
        defaults="channel-defaults-0.csv",
        freq_decimals=5,
        talkgroup_notes=False,
        member_freqs=False,
    ),
    "1": CpsFormat(
        name="1",
        defaults="channel-defaults-1.csv",
    ),
    "2": CpsFormat(
        name="2",
        defaults="channel-defaults-2.csv",
        columns=FORMAT_2_COLUMNS,
        freq_decimals=5,
        zone_hide=True,
        talkgroup_notes=False,
    ),
    "3": CpsFormat(
        name="3",
        defaults="channel-defaults-3.csv",
        columns=FORMAT_3_COLUMNS,
        freq_decimals=5,
        zone_hide=True,
        talkgroup_notes=False,
        files=FORMAT_3_FILES,
        airband=True,
    ),
}


class ConfigError(Exception):
    """A fatal problem with the input data.  Reported to the user, then we stop."""


def warning(message):
    print(f"WARNING: {message}")


def report_error(message):
    sys.stderr.write("ERROR: " + message + ("" if message.endswith("\n") else "\n"))


################################################################################
##########   PERL-ISMS
################################################################################

_NUMBER_RE = re.compile(r"\s*[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?\s*\Z")
_LEADING_NUMBER_RE = re.compile(r"\s*[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def looks_like_number(value):
    if isinstance(value, (int, float)):
        return True
    if value is None:
        return False
    return bool(_NUMBER_RE.match(value))


def perl_num(value):
    """Perl's numeric coercion of a scalar: the leading number, or 0."""
    if isinstance(value, (int, float)):
        return value
    match = _LEADING_NUMBER_RE.match(value or "")
    return float(match.group()) if match and match.group().strip() else 0.0


def perl_split(sep, value):
    """split() the Perl way: trailing empty fields are dropped."""
    parts = (value or "").split(sep)
    while parts and parts[-1] == "":
        parts.pop()
    return parts


def open_csv_read(filename):
    try:
        return open(filename, newline="", encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Couldn't open file '{filename}': {exc.strerror}\n")


def csv_writer(fh):
    return csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator="\r\n")


################################################################################
##########   DATA VALIDATION ROUTINES
################################################################################

# The Perl original appended this suffix to every validation error, built from
# globals that start out as line 0 of file 'none' -- so errors raised before any
# input file is open (the command-line mode checks) carry it too.
NO_FILE_CONTEXT = " [On line #0 of none file.]\n"


def validate_bandwidth(mode, ctx=NO_FILE_CONTEXT):
    return _validate_membership(mode, ("25K", "12.5K"), "Analog Mode", ctx)


def validate_call_type(call_type, ctx=NO_FILE_CONTEXT):
    return _validate_membership(call_type, ("Private Call", "Group Call"), "Call Type", ctx)


def validate_channel_name(contact, ctx=NO_FILE_CONTEXT):
    return _validate_string_length("Channel Name", contact, LENGTH_CHAN_NAME, ctx)


def validate_color_code(color_code, ctx=NO_FILE_CONTEXT):
    return _validate_num_in_range("Color Code", color_code, 0, 16, ctx)


def validate_contact(contact, ctx=NO_FILE_CONTEXT):
    return _validate_string_length("Contact (aka Talk Group)", contact, LENGTH_CHAN_NAME, ctx)


def validate_ctcss(ctcss, ctx=NO_FILE_CONTEXT):
    if ctcss == "Off":
        return ctcss
    if re.search(r"D[0-9A-Za-z]+", ctcss or "") and len(ctcss) < 10:  # DCS tones, could be smarter
        return ctcss
    return _validate_num_in_range("CTCSS/DCS", ctcss, 0, 300, ctx)  # this could be smarter


def validate_freq(freq, ctx=NO_FILE_CONTEXT):
    return _validate_num_in_range("Frequency", freq, 0, 500, ctx)  # this could be smarter too


def validate_name(name, ctx=NO_FILE_CONTEXT):
    return _validate_string_length("Channel Name", name, LENGTH_CHAN_NAME, ctx)


def validate_power(power, ctx=NO_FILE_CONTEXT):
    return _validate_membership(power, ("Low", "Mid", "High", "Turbo"), "Power Level", ctx)


def validate_timeslot(timeslot, ctx=NO_FILE_CONTEXT):
    return _validate_membership(timeslot, ("1", "2", "-"), "Time Slot", ctx)


def validate_tx_permit(tx_permit, ctx=NO_FILE_CONTEXT):
    valid = ("Always", "ChannelFree", "Same Color Code", "Different Color Code")
    return _validate_membership(tx_permit, valid, "TX Permit", ctx)


def validate_tx_prohibit(tx_prohibit, ctx=NO_FILE_CONTEXT):
    return _validate_on_off(tx_prohibit, "TX Prohibit", ctx)


def validate_zone(zone, ctx=NO_FILE_CONTEXT):
    return _validate_string_length("Zone", zone, 16, ctx)


def validate_sort_mode(sort_order):
    valid = ("alpha", "repeaters-first", "analog-first")
    return _validate_membership(sort_order, valid, "Sort Order")


def validate_hotspot_mode(hotspot_mode):
    return _validate_membership(hotspot_mode, ("always", "same-color-code"), "Hotspot TX Permit")


def validate_cps_format(cps_format):
    return _validate_membership(cps_format, tuple(CPS_FORMATS), "CPS Format")


def validate_nickname_mode(nickname_mode):
    valid = ("off", "prefix", "suffix", "prefix-forced", "suffix-forced")
    return _validate_membership(nickname_mode, valid, "Nickname Mode")


####
# Validation Helpers
####

def _validate_membership(value, valid_set, error_name, ctx=NO_FILE_CONTEXT):
    if value not in valid_set:
        raise ConfigError(
            f"Invalid {error_name}: '{'' if value is None else value}' is not one of: "
            + ", ".join(valid_set)
            + ctx
        )
    return value


def _validate_num_in_range(type_name, value, minimum, maximum, ctx=NO_FILE_CONTEXT):
    if not looks_like_number(value) or not (minimum <= float(value) <= maximum):
        raise ConfigError(
            f"Invalid {type_name}: '{'' if value is None else value}' must be an number "
            f"between {minimum} and {maximum} (inclusive)" + ctx
        )
    return value


def _validate_on_off(value, error_name, ctx=NO_FILE_CONTEXT):
    return _validate_membership(value, ("On", "Off"), error_name, ctx)


def _validate_string_length(type_name, string, length, ctx=NO_FILE_CONTEXT):
    # The Perl original stopped here.  We report the same message but carry on
    # with the value truncated to fit, so one over-long name doesn't cost you the
    # whole build.
    if len(string or "") > length:
        truncated = string[:length]
        report_error(f"Invalid {type_name}: '{string}' is more than {length} characters, "
                     f"truncated to '{truncated}'" + ctx)
        return truncated
    return string


################################################################################
##########   THE BUILDER
################################################################################

class ConfigBuilder:
    def __init__(self, sort_mode="alpha", hotspot_tx_permit="same-color-code",
                 nickname_mode="prefix", cps_format="1"):
        self.cps_format = CPS_FORMATS[cps_format]
        self.sort_mode = sort_mode
        self.hotspot_tx_permit = hotspot_tx_permit
        self.nickname_mode = nickname_mode

        self.line_number = 0
        self.file_name = "none"
        self.channel_number = 1

        self.channel_csv_field_name = {}
        self.channel_csv_default_value = {}
        self.talkgroup_mapping = {}
        self.talkgroup_order = {}
        self.zone_config = {}
        self.zone_order = {}
        self.zone_order_default = 9999  # this impacts where the analog and digital-others go.
        self.analog_channel_index = 0
        self.scanlist_config = {}
        self.talkgroup_config = {}
        self.am_air = {}          # airband channel name -> frequency, first seen first
        self.am_zone_config = {}  # airband zone name -> its channel names, in order

    def run(self, analog_filename, digital_others_filename, digital_repeaters_filename,
            talkgroups_filename, config_directory, output_directory,
            airband_filename=None):
        files = self.cps_format.files

        self.read_talkgroups(talkgroups_filename)
        self.read_channel_csv_default(f"{config_directory}/{self.cps_format.defaults}")

        try:
            fh = open(f"{output_directory}/{files['channels']}", "w",
                      newline="", encoding="utf-8")
        except OSError:
            raise ConfigError(f"Couldn't open {files['channels']} for writing\n")

        with fh:
            out = csv_writer(fh)
            self.print_channel_header(out)
            self.process_dmr_others_file(out, digital_others_filename)
            self.process_dmr_repeater_file(out, digital_repeaters_filename)
            self.process_analog_file(out, analog_filename)

        self.write_zone_file(f"{output_directory}/{files['zones']}")
        self.write_scanlist_file(f"{output_directory}/{files['scanlists']}")
        self.write_talkgroup_file(f"{output_directory}/{files['talkgroups']}")

        # Airband is optional, and its absence is the normal case -- without it the
        # CPS simply keeps whatever airband channels the radio already holds.
        if airband_filename is not None:
            self.read_airband_file(airband_filename)
            self.write_am_air_file(f"{output_directory}/{AM_FILES['am_air']}")
            self.write_am_zone_file(f"{output_directory}/{AM_FILES['am_zones']}")

            if not self.cps_format.airband:
                warning(f"The airband files are only read by AT-D890UV CPS 1.05, which "
                        f"is --cps-format=3. {AM_FILES['am_air']} and "
                        f"{AM_FILES['am_zones']} have been written, but the CPS that "
                        f"--cps-format={self.cps_format.name} targets will not import "
                        f"them.")

    ############################################################################
    ##########   CSV OUTPUT ROUTINES
    ############################################################################

    #####
    ##### Zone file output #####
    #####
    def write_zone_file(self, filename):
        headers = ["No.", "Zone Name", "Zone Channel Member"]
        if self.cps_format.member_freqs:
            headers.extend(["Zone Channel Member RX Frequency",
                            "Zone Channel Member TX Frequency"])

        for side in ("A", "B"):
            headers.append(f"{side} Channel")
            if self.cps_format.member_freqs:
                headers.extend([f"{side} Channel RX Frequency",
                                f"{side} Channel TX Frequency"])

        if self.cps_format.zone_hide:
            headers.append("Zone Hide ")

        self.generate_csv_file(filename, headers, self.zone_config,
                               self.zone_row_builder, cmp_to_key(self.zone_sort))

    def write_scanlist_file(self, filename):
        headers = ["No.", "Scan List Name", "Scan Channel Member"]
        if self.cps_format.member_freqs:
            headers.extend(["Scan Channel Member RX Frequency",
                            "Scan Channel Member TX Frequency"])

        headers.extend(["Scan Mode", "Priority Channel Select"])
        for priority in (1, 2):
            headers.append(f"Priority Channel {priority}")
            if self.cps_format.member_freqs:
                headers.extend([f"Priority Channel {priority} RX Frequency",
                                f"Priority Channel {priority} TX Frequency"])

        headers.extend(["Revert Channel", "Look Back Time A[s]",
                        "Look Back Time B[s]", "Dropout Delay Time[s]",
                        "Dwell Time[s]"])

        self.generate_csv_file(filename, headers, self.scanlist_config,
                               self.scanlist_row_builder, case_insensitive_key)

    def write_talkgroup_file(self, filename):
        headers = ["No.", "Radio ID", "Name"]
        if self.cps_format.talkgroup_notes:
            headers.extend(["Country", "Remarks"])
        headers.extend(["Call Type", "Call Alert"])

        self.generate_csv_file(filename, headers, self.talkgroup_config,
                               self.talkgroup_row_builder, case_insensitive_key)

    #####
    ##### Airband file output #####
    #####
    def write_am_air_file(self, filename):
        """The flat airband channel table: every channel any AM zone names."""
        self.generate_csv_file(filename, ["No.", "Frequency[MHz]", "Name"],
                               self.am_air, self.am_air_row_builder,
                               list(self.am_air).index)

    def write_am_zone_file(self, filename):
        # "Scan Channel " really does carry that trailing space, the same way
        # "Zone Hide " does on the DMR zones.
        self.generate_csv_file(filename,
                               ["No.", "Zone Name", "Zone Channel Member",
                                "A Channel", "Scan Channel "],
                               self.am_zone_config, self.am_zone_row_builder,
                               case_insensitive_key)

    def am_air_row_builder(self, air_number, chan_name, frequency):
        return [air_number, frequency, chan_name]

    def am_zone_row_builder(self, zone_number, zone_name, channels):
        # Unlike a DMR zone, there is no B channel to mirror: the airband receiver
        # is picked on the radio ("AM Mode A" / "AM Mode B"), so this lone column
        # is the zone's default channel rather than one receiver's.  Scan Channel
        # is left unset, as the CPS itself exports it.
        return [zone_number, zone_name, "|".join(channels),
                channels[0] if channels else "", ""]

    def zone_row_builder(self, zone_number, zone_name, zone_record):
        def details(values, channel0, rx0, tx0):
            # A Channel and B Channel, both the zone's first channel by name.
            for _ in ("A", "B"):
                values.append(channel0)
                if self.cps_format.member_freqs:
                    values.extend([rx0, tx0])

        values = self.generic_row_builder(zone_number, zone_name, zone_record,
                                          details, 250, "Zone")
        if self.cps_format.zone_hide:
            values.append("0")

        return values

    def scanlist_row_builder(self, scan_number, scan_name, scan_record):
        def details(values, _channel0, _rx0, _tx0):
            values.extend(SCANLIST_DETAILS if self.cps_format.member_freqs
                          else SCANLIST_DETAILS_NO_FREQS)

        return self.generic_row_builder(scan_number, scan_name, scan_record,
                                        details, 50, "Scanlist")

    def talkgroup_row_builder(self, tg_number, talkgroup_name, _junk):
        call_type = self.talkgroup_config[talkgroup_name]

        row = [tg_number,
               self.talkgroup_mapping[talkgroup_name],
               talkgroup_name]
        if self.cps_format.talkgroup_notes:
            row.extend(["", ""])          # Country, Remarks

        row.extend([call_type, "None"])

        return row

    def generic_row_builder(self, row_number, row_name, row_record, row_func, row_limit, warning_name):
        values = [row_number, row_name]

        channels = []
        rx_freqs = []
        tx_freqs = []
        for i, row_details in enumerate(sorted(row_record, key=case_insensitive_key)):
            _order, chan_name, rx_freq, tx_freq = row_details.split("\t")
            # TODO: This sort of trimming should live WAAAAY higher elsewhere
            chan_name = re.sub(r"\s+$", "", chan_name)

            if row_limit > 0 and i >= row_limit:
                warning(f"{warning_name} '{row_name}' has more than {row_limit} channels. "
                        f"It has been truncated to the first {row_limit} channels to keep "
                        f"the CPS software happy.")
                break

            channels.append(chan_name)
            rx_freqs.append(rx_freq)
            tx_freqs.append(tx_freq)

        values.append("|".join(channels))
        if self.cps_format.member_freqs:
            values.append("|".join(rx_freqs))
            values.append("|".join(tx_freqs))
        row_func(values,
                 channels[0] if channels else "",
                 rx_freqs[0] if rx_freqs else "",
                 tx_freqs[0] if tx_freqs else "")
        return values

    #####
    #####  Generic CSV file writer given a dict of data
    #####
    def generate_csv_file(self, filename, headers, data, row_func, sort_key):
        try:
            fh = open(filename, "w", newline="", encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Couldn't open file '{filename}': {exc.strerror}\n")

        with fh:
            out = csv_writer(fh)
            out.writerow(headers)

            for row_num, key in enumerate(sorted(data, key=sort_key), start=1):
                out.writerow(row_func(row_num, key, data[key]))

    def print_channel_header(self, out):
        out.writerow([self.channel_csv_field_name[index]
                      for index in sorted(self.channel_csv_field_name)])

    ##########
    ####  Sort Functions
    ##########
    def zone_sort(self, a, b):
        a_i = self.zone_order[a]
        b_i = self.zone_order[b]

        # If we're in alphabetical mode or if the zone indexes are the same (which will be the case
        # if we're in non-alphabetical mode for the analog and digital-other channels).
        if self.sort_mode == "alpha" or a_i == b_i:
            return cmp(a.lower(), b.lower())
        return cmp(a_i, b_i)

    ############################################################################
    ##########   CSV INPUT ROUTINES
    ############################################################################

    #####
    #  Analog CSV
    #####
    def process_analog_file(self, out, filename):
        header = ["Zone", "Channel Name", "Bandwidth", "Power",
                  "RX Freq", "TX Freq", "CTCSS Decode", "CTCSS Encode",
                  "TX Prohibit"]

        self.process_csv_file_with_header(out, filename, "Analog", header,
                                          self.analog_csv_field_extractor)

    def analog_csv_field_extractor(self, row):
        ctx = self._file_and_line()

        chan_config = {
            CHAN_SCANLIST_NAME: validate_zone(row[0], ctx),
            CHAN_NAME: validate_name(row[1], ctx),
            CHAN_BANDWIDTH: validate_bandwidth(row[2], ctx),
            CHAN_POWER: validate_power(row[3], ctx),
            CHAN_RX_FREQ: self.cps_format.freq(validate_freq(row[4], ctx)),
            CHAN_TX_FREQ: self.cps_format.freq(validate_freq(row[5], ctx)),
            CHAN_CTCSS_DEC: validate_ctcss(row[6], ctx),
            CHAN_CTCSS_ENC: validate_ctcss(row[7], ctx),
            CHAN_TX_PROHIBIT: validate_tx_prohibit(row[8], ctx),
            CHAN_PTT_PROHIBIT: validate_tx_prohibit(row[8], ctx),
            CHAN_MODE: VAL_ANALOG,
        }

        if chan_config[CHAN_CTCSS_DEC] != "Off":
            chan_config[CHAN_SQUELCH_MODE] = VAL_CTCSS_DCS

        return chan_config

    #####
    ## DMR Others CSV
    #####
    def process_dmr_others_file(self, out, filename):
        header = ["Zone", "Channel Name", "Power", "RX Freq", "TX Freq", "Color Code",
                  "Talk Group", "TimeSlot", "Call Type", "TX Permit"]

        self.process_csv_file_with_header(out, filename, "Digital-Others", header,
                                          self.dmr_others_csv_field_extractor)

    def dmr_others_csv_field_extractor(self, row):
        ctx = self._file_and_line()

        chan_config = {
            CHAN_SCANLIST_NAME: validate_zone(row[0], ctx),
            CHAN_NAME: validate_name(row[1], ctx),
            CHAN_POWER: validate_power(row[2], ctx),
            CHAN_RX_FREQ: self.cps_format.freq(validate_freq(row[3], ctx)),
            CHAN_TX_FREQ: self.cps_format.freq(validate_freq(row[4], ctx)),
            CHAN_COLOR_CODE: validate_color_code(row[5], ctx),
            CHAN_CONTACT: validate_contact(row[6], ctx),
            CHAN_TG_ID: self.talkgroup_mapping.get(row[6]),
            CHAN_TIME_SLOT: validate_timeslot(row[7], ctx),
            CHAN_CALL_TYPE_OLD: validate_call_type(row[8], ctx),
            CHAN_CALL_TYPE_NEW: validate_call_type(row[8], ctx),
            CHAN_TX_PERMIT: validate_tx_permit(row[9], ctx),
            CHAN_MODE: VAL_DIGITAL,
        }
        chan_config[CHAN_DMR_MODE] = dmr_mode(chan_config)

        return chan_config

    #####
    # DMR Repeater CSV
    #####
    def process_dmr_repeater_file(self, out, filename):
        header = ["Zone Name", "Comment", "Power", "RX Freq", "TX Freq", "Color Code"]

        self.process_csv_file_with_header(out, filename, "Digital-Repeater", header,
                                          self.dmr_repeater_csv_field_extractor,
                                          self.dmr_repeater_csv_matrix_extractor)

    def dmr_repeater_csv_field_extractor(self, row):
        ctx = self._file_and_line()

        zone_full, zone_nick = handle_nickname_values(row[0])

        chan_config = {
            CHAN_SCANLIST_NAME: validate_zone(zone_full, ctx),
            ACB_ZONE_NICKNAME: validate_zone(zone_nick, ctx),
            # row[1] is a comment column
            CHAN_POWER: validate_power(row[2], ctx),
            CHAN_RX_FREQ: self.cps_format.freq(validate_freq(row[3], ctx)),
            CHAN_TX_FREQ: self.cps_format.freq(validate_freq(row[4], ctx)),
            CHAN_COLOR_CODE: validate_color_code(row[5], ctx),
            CHAN_MODE: VAL_DIGITAL,
        }
        chan_config[CHAN_DMR_MODE] = dmr_mode(chan_config)

        return chan_config

    def dmr_repeater_csv_matrix_extractor(self, chan_config, contact, value):
        ctx = self._file_and_line()
        do_multiply = False

        timeslot, call_type = handle_repeater_value(value)

        timeslot = validate_timeslot(timeslot, ctx)
        if timeslot != VAL_NO_TIME_SLOT:
            contact, chan_nick = handle_nickname_values(contact)

            chan_name = self.make_channel_name(chan_config[ACB_ZONE_NICKNAME], contact, chan_nick)

            chan_config[CHAN_CONTACT] = validate_contact(contact, ctx)
            chan_config[CHAN_TG_ID] = self.talkgroup_mapping.get(contact)
            chan_config[CHAN_TIME_SLOT] = validate_timeslot(timeslot, ctx)
            chan_config[CHAN_NAME] = validate_channel_name(chan_name, ctx)
            chan_config[CHAN_CALL_TYPE_OLD] = validate_call_type(call_type, ctx)
            chan_config[CHAN_CALL_TYPE_NEW] = validate_call_type(call_type, ctx)
            do_multiply = True

        return do_multiply, chan_config

    #####
    #####
    ## These two routines are basically the same... let's extract the common parts
    ## and make this generic
    #####
    #####
    def read_channel_csv_default(self, filename):
        with open_csv_read(filename) as fh:
            for row in csv.reader(fh):
                if not row:
                    continue
                index = int(perl_num(row[0]))
                self.channel_csv_field_name[index] = row[1]
                self.channel_csv_default_value[index] = row[2]

    def read_airband_file(self, filename):
        """Read the airband input into the flat channel table and its zones.

        Deliberately not process_csv_file_with_header(): that one is welded to the
        channel pipeline, and an airband channel is in no zone, scanlist or
        talkgroup that pipeline builds.  The header check matches it, though.

        One row per channel per zone.  A name in two zones is one airband channel
        with two memberships, not two channels -- which is the one way this file
        differs from the analog one, where a repeat means a second channel.
        """
        header = ["Zone", "Channel Name", "Frequency"]
        saved = (self.file_name, self.line_number)
        self.file_name = "Airband"

        try:
            with open_csv_read(filename) as fh:
                for line_no, row in enumerate(csv.reader(fh)):
                    if not row:
                        continue
                    self.line_number = line_no

                    if line_no == 0:
                        for col in range(len(header)):
                            found = row[col] if col < len(row) else ""
                            if found != header[col]:
                                raise ConfigError(
                                    f"CSV header does not match for Airband file "
                                    f"(found '{found}' expected '{header[col]}')\n")
                        continue

                    ctx = self._file_and_line()
                    zone = validate_zone(row[0], ctx)
                    name = _validate_string_length("Airband Channel Name", row[1],
                                                   LENGTH_AM_NAME, ctx)
                    freq = f"{float(validate_freq(row[2], ctx)):.{AM_FREQ_DECIMALS}f}"

                    # The table is keyed by name, so one name cannot hold two
                    # frequencies -- that has to be the input being wrong.
                    if self.am_air.setdefault(name, freq) != freq:
                        raise ConfigError(
                            f"Airband channel '{name}' is {self.am_air[name]} MHz "
                            f"elsewhere, but {freq} MHz here. One name cannot be two "
                            f"frequencies." + ctx)

                    members = self.am_zone_config.setdefault(zone, [])
                    if name not in members:
                        members.append(name)
        finally:
            self.file_name, self.line_number = saved

    def read_talkgroups(self, filename):
        # Key on the same shortened form validate_contact() produces downstream.
        # A channel referring to an over-long talkgroup arrives here truncated, so
        # without this it would look like a talkgroup that was never defined.
        saved = (self.file_name, self.line_number)
        self.file_name = "Talkgroup"
        originals = {}
        try:
            with open_csv_read(filename) as fh:
                for index, row in enumerate(csv.reader(fh), start=1):
                    if not row:
                        continue
                    self.line_number = index - 1
                    name = validate_contact(row[0], self._file_and_line())

                    if originals.get(name, row[0]) != row[0]:
                        warning(f"Talkgroups '{originals[name]}' and '{row[0]}' both "
                                f"shorten to '{name}', so the radio cannot tell them "
                                f"apart. Using the last one.")
                    originals[name] = row[0]

                    # A stray space around an ID reaches both channels.csv and
                    # talkgroups.csv, where the CPS wants a bare number.
                    self.talkgroup_mapping[name] = row[1].strip()
                    self.talkgroup_order[name] = index
        finally:
            self.file_name, self.line_number = saved

    #####
    #####
    ## This is where a lot of the magic happens...
    #####
    #####

    # This is where we read the input CSV files.  This is a fairly generic routine that is driven by
    # its arguments.  Specifically, it takes a few callables to do the actual "hard work" of
    # extracting the relevant fields into a "chan_config" dict which then gets passed into the
    # add_channel routine at the end.
    #
    # This is made slightly more interesting/complicated by the fact that our repeaters input has a
    # few columns that are the same for every channel (frequencies and such), but then has a big
    # matrix of talk groups that are available on the repeater.  So, this routine ALSO does the
    # "matrix multiplication" (probably a poor word choice) by extracting the talk group names and
    # then multiplying out the row into a channel for each talkgroup that's on the repeater.
    #
    def process_csv_file_with_header(self, out, filename, file_nickname, header,
                                     field_extractor, matrix_field_extractor=None):
        headers = []

        self.file_name = file_nickname

        zone_order_index = 1
        with open_csv_read(filename) as fh:
            for line_no, row in enumerate(csv.reader(fh)):
                if not row:
                    continue
                self.line_number = line_no

                # Make sure the header looks sane... it's an easy check, but it'll catch obvious
                # mistakes
                if line_no == 0:
                    # iterate through the headers that were provided in the arguments and make sure
                    # they match what's in the file.
                    for col in range(len(header)):
                        found = row[col] if col < len(row) else ""
                        if found != header[col]:
                            raise ConfigError(
                                f"CSV header does not match for {file_nickname} file "
                                f"(found '{found}' expected '{header[col]}')\n")
                        headers.append(found)

                    # If this is going to be a matrix'd CSV, those headers will follow the main
                    # headers
                    headers.extend(row[len(header):])
                    continue

                ## Process an actual data row...
                chan_config = field_extractor(row)
                zone_name = chan_config[CHAN_SCANLIST_NAME]

                # non-matrixed CSV files:
                if len(header) == len(row):
                    # This area applies to the Analog and "Other DMR" inputs...
                    # Each of those files has a "zone" column.  We'll create a zone and a scanlist
                    # with all the channels listed in the specified zone.
                    # ... this is a hack and shouldn't live here =/
                    scanlist_name = chan_config[CHAN_SCANLIST_NAME]

                    self.add_channel(out, chan_config, zone_name, scanlist_name,
                                     self.zone_order_default)

                # matrixed CSV files... so iterate through each of the extra headers, which are the
                # talk groups...
                for col in range(len(header), len(row)):
                    if matrix_field_extractor is None:
                        raise ConfigError(
                            f"There are too many columns in '{file_nickname}' file, "
                            f"line {line_no}.\n")
                    if col >= len(headers):
                        raise ConfigError(
                            f"Line {line_no} of the '{file_nickname}' file has more columns "
                            f"than the header row.\n")

                    do_matrix, chan_config = matrix_field_extractor(chan_config, headers[col],
                                                                    row[col])

                    if do_matrix:
                        # For the repeaters, we create a zone per repeater, and a scanlist for each
                        # talkgroup (which allows us to scan this talkgroup across all repeaters).
                        # We also set the scanlist_name to the talkgroup so that when we hit scan,
                        # we actually scan the right thing ;-P
                        #
                        # again, this is a hack and shouldn't live here.
                        scanlist_name = chan_config[CHAN_CONTACT]
                        chan_config[CHAN_SCANLIST_NAME] = scanlist_name

                        chan_config[CHAN_TX_PERMIT] = self.tx_permit(chan_config)

                        self.add_channel(out, chan_config, zone_name, scanlist_name,
                                         zone_order_index)
                zone_order_index += 1

    def add_channel(self, out, chan_config, zone_name, scanlist_name, zone_order_index):
        output = []

        for column in sorted(self.channel_csv_default_value):
            # Which of our internal fields, if any, this CPS wants in this column.
            field = self.cps_format.field_for_column(column)

            value = self.channel_csv_default_value[column]
            if field is not None and chan_config.get(field) is not None:
                value = chan_config[field]
            if field == CHAN_NUM:
                value = self.channel_number
                self.channel_number += 1

            if field is not None:
                chan_config[field] = value

            if value == "REQUIRED":
                raise ConfigError(
                    f"I need a value for '{self.channel_csv_field_name[column]}'\n")

            output.append(value)

        out.writerow(output)

        self.build_zone_config(chan_config, zone_name, zone_order_index)
        self.build_scanlist_config(chan_config, scanlist_name)
        if chan_config[CHAN_MODE] == VAL_DIGITAL:
            self.build_talkgroup_config(chan_config, zone_name)

    def build_zone_config(self, chan_config, zone_name, zone_order_index):
        self.zone_order[zone_name] = zone_order_index

        order = self.channel_order_name(chan_config)
        self.zone_config.setdefault(zone_name, []).append(
            "\t".join([order,
                       chan_config[CHAN_NAME],
                       str(chan_config[CHAN_RX_FREQ]),
                       str(chan_config[CHAN_TX_FREQ])]))

    def build_scanlist_config(self, chan_config, scanlist_name):
        order = self.channel_order_name(chan_config)
        self.scanlist_config.setdefault(scanlist_name, []).append(
            "\t".join([order,
                       chan_config[CHAN_NAME],
                       str(chan_config[CHAN_RX_FREQ]),
                       str(chan_config[CHAN_TX_FREQ])]))

    def build_talkgroup_config(self, chan_config, zone_name):
        talkgroup = chan_config[CHAN_CONTACT]
        call_type = chan_config[CHAN_CALL_TYPE_OLD]

        if talkgroup not in self.talkgroup_mapping:
            raise ConfigError(f"Talkgroup '{talkgroup}' is referenced but not defined in the "
                              f"talkgroup input CSV file\n")

        if talkgroup in self.talkgroup_config and self.talkgroup_config[talkgroup] != call_type:
            other_call_type = self.talkgroup_config[talkgroup]
            chan_name = chan_config[CHAN_NAME]
            rx_freq = chan_config[CHAN_RX_FREQ]
            tx_freq = chan_config[CHAN_TX_FREQ]

            raise ConfigError(
                f"Talkgroup '{talkgroup}' was previously identified as a '{other_call_type}', "
                f"but is now trying to be used as a '{call_type}' on channel '{chan_name}' "
                f"(Zone: '{zone_name}', RX: {rx_freq}, TX: {tx_freq}).  The Anytone CPS won't "
                f"allow this to be imported.   To fix this, create a second entry in your "
                f"talkgroups CSV input file for this talkgroup with a different name.\n")

        self.talkgroup_config[talkgroup] = call_type

    def channel_order_name(self, chan_config):
        index1 = self.zone_order_default
        index2 = 0
        chan_name = chan_config[CHAN_NAME]

        if self.sort_mode != "alpha":
            if chan_config[CHAN_MODE] == VAL_DIGITAL:
                if chan_config[CHAN_CONTACT] in self.talkgroup_order:
                    index1 = self.talkgroup_order[chan_config[CHAN_CONTACT]]
            elif chan_config[CHAN_MODE] == VAL_ANALOG:
                index2 = self.analog_channel_index
                self.analog_channel_index += 1

        return f"{index1:04d}{index2:04d}{chan_name}"

    def tx_permit(self, chan_config):
        if (self.hotspot_tx_permit == "always"
                and chan_config[CHAN_RX_FREQ] == chan_config[CHAN_TX_FREQ]):
            return VAL_TX_PERMIT_ALWAYS

        return VAL_TX_PERMIT_SAME

    def make_channel_name(self, zone_nick, chan_full, chan_nick):
        if self.nickname_mode == "off" or len(zone_nick) == 0:
            return chan_full

        if len(chan_nick) == 0:
            chan_nick = chan_full

        if self.nickname_mode in ("prefix-forced", "suffix-forced"):
            chan_full = chan_nick

        if len(zone_nick) + len(chan_full) + 1 <= LENGTH_CHAN_NAME:
            chan_name, sep = chan_full, " "
        elif len(zone_nick) + len(chan_nick) + 1 <= LENGTH_CHAN_NAME:
            chan_name, sep = chan_nick, " "
        elif len(zone_nick) + len(chan_nick) <= LENGTH_CHAN_NAME:
            chan_name, sep = chan_nick, ""
        else:
            raise ConfigError(f"Can't make a channel name fit into 16 characters for "
                              f"'{zone_nick}' and '{chan_nick}'")

        # some people like to prefix their nicknames with "-" or "/", drop the space in that case
        if not re.match(r"[A-Za-z0-9]", zone_nick):
            sep = ""

        if self.nickname_mode in ("prefix", "prefix-forced"):
            return zone_nick + sep + chan_name

        return chan_name + sep + zone_nick

    def _file_and_line(self):
        return f" [On line #{self.line_number} of {self.file_name} file.]\n"


################################################################################
##########   MODULE-LEVEL HELPERS
################################################################################

def cmp(a, b):
    return (a > b) - (a < b)


def case_insensitive_key(value):
    # no fancy scanning rules here
    return value.lower()


def dmr_mode(chan_config):
    if chan_config[CHAN_RX_FREQ] != chan_config[CHAN_TX_FREQ]:
        return VAL_DMR_MODE_REPEATER

    return VAL_DMR_MODE_SIMPLEX


def handle_repeater_value(value):
    subvalues = perl_split(";", value)

    timeslot = subvalues.pop(0) if subvalues else ""

    call_type = VAL_CALL_TYPE_GROUP
    for v in subvalues:
        if v == "P":
            call_type = VAL_CALL_TYPE_PRIVATE

    return timeslot, call_type


def handle_nickname_values(value):
    #  OLY;Olympia/Cap Pk.
    subvalues = perl_split(";", value)

    full = subvalues.pop(0) if subvalues else ""
    nick = ""
    for v in subvalues:
        nick = v

    return full, nick


################################################################################
##########   GENERIC STUFF: usage(), command-line args, etc
################################################################################

def usage():
    print(f"{sys.argv[0]} ")
    print("arguments:")
    print("  --analog-csv=<analog.csv>  ")
    print("  --digital-others-csv=<digital-others.csv>")
    print("  --digital-repeaters-csv=<digital_repeaters.csv> ")
    print("  --talkgroups-csv=<talkgroups.csv> ")
    print("  --output-directory=<output-directory>")
    print("  [--am-air-csv=<airband.csv>]")
    print("  [--config=<config file>]")
    print("  [--sorting=(alpha|repeaters-first|analog-first)]")
    print("  [--hotspot-tx-permit=(always|same-color-code)]")
    print("  [--nicknames=(off|prefix|suffix)]")
    print("  [--cps-format=(0|1|2|3)]")
    sys.exit(255)


def handle_command_line_args(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--analog-csv")
    parser.add_argument("--digital-others-csv")
    parser.add_argument("--digital-repeaters-csv")
    parser.add_argument("--talkgroups-csv")
    parser.add_argument("--am-air-csv")
    parser.add_argument("--config")
    parser.add_argument("--output-directory")
    parser.add_argument("--sorting", default="alpha")
    parser.add_argument("--nicknames", default="prefix")
    parser.add_argument("--hotspot-tx-permit", default="same-color-code")
    parser.add_argument("--cps-format", default="1")

    if "--" in argv:
        argv = argv[:argv.index("--")]

    try:
        args, extra = parser.parse_known_args(argv)
    except SystemExit:
        usage()

    # Getopt::Long leaves non-option arguments in @ARGV without complaint, but
    # warns on stderr for anything that looks like an unrecognized option.
    unknown = [a for a in extra if a.startswith("-")]
    if unknown:
        for opt in unknown:
            sys.stderr.write("Unknown option: "
                             + opt.lstrip("-").split("=", 1)[0].lower() + "\n")
        usage()

    validate_sort_mode(args.sorting)
    validate_hotspot_mode(args.hotspot_tx_permit)
    validate_nickname_mode(args.nicknames)
    validate_cps_format(args.cps_format)

    if (args.analog_csv is None or args.digital_others_csv is None
            or args.digital_repeaters_csv is None or args.talkgroups_csv is None
            or args.output_directory is None):
        usage()

    if args.config is None:
        args.config = "config"

    return args


def main(argv=None):
    args = handle_command_line_args(sys.argv[1:] if argv is None else argv)

    builder = ConfigBuilder(sort_mode=args.sorting,
                            hotspot_tx_permit=args.hotspot_tx_permit,
                            nickname_mode=args.nicknames,
                            cps_format=args.cps_format)

    if args.sorting == "analog-first":
        builder.zone_order_default = 0

    builder.run(args.analog_csv, args.digital_others_csv, args.digital_repeaters_csv,
                args.talkgroups_csv, args.config, args.output_directory,
                airband_filename=args.am_air_csv)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as exc:
        report_error(str(exc))
        sys.exit(255)
