"""Unit tests for ApexTimingWebSocketParser.

Focuses on message parsing, column mapping, and time-parsing helpers.
No database, no WebSocket connection — pure unit tests.
"""

import pytest

from apex_timing_websocket import ApexTimingWebSocketParser


# ---------------------------------------------------------------------------
# Inline time-parsing helpers (identical to race_ui.py:745-765).
# We duplicate them here rather than importing from race_ui to avoid
# triggering module-level Flask / TrackDatabase / SocketIO side effects.
# ---------------------------------------------------------------------------

def _parse_time_to_seconds(time_str):
    """Convert a time string (MM:SS.sss or SS.sss) to seconds.

    Returns float('inf') for empty/None input; raises ValueError on malformed.
    Commas are tolerated as decimal separators (some Apex feeds emit them).
    """
    if not time_str:
        return float('inf')
    s = time_str.replace(',', '.')
    if ':' in s:
        parts = s.split(':')
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    return float(s)


def _safe_parse_time(time_str, default=float('inf')):
    try:
        return _parse_time_to_seconds(time_str)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# parse_websocket_message
# ---------------------------------------------------------------------------

class TestParseWebSocketMessage:
    """Tests for parse_websocket_message — pipe-delimited message parsing."""

    def test_grid_init_message(self):
        """A grid|html|... message splits into command/parameter/value."""
        parser = ApexTimingWebSocketParser()
        result = parser.parse_websocket_message(
            "grid|html|<table><tr class='head'>...</tr></table>"
        )
        assert result == {
            'command': 'grid',
            'parameter': 'html',
            'value': "<table><tr class='head'>...</tr></table>",
        }

    def test_update_pos_message(self):
        """An upd|pos|... message splits correctly."""
        parser = ApexTimingWebSocketParser()
        result = parser.parse_websocket_message("upd|pos|1|2|3|4")
        assert result == {
            'command': 'upd',
            'parameter': 'pos',
            'value': '1|2|3|4',
        }

    def test_update_with_only_two_parts(self):
        """When there are exactly two pipe-delimited parts, value is empty."""
        parser = ApexTimingWebSocketParser()
        result = parser.parse_websocket_message("cmd|param")
        assert result == {'command': 'cmd', 'parameter': 'param', 'value': ''}

    def test_empty_message_returns_empty_dict(self):
        """Empty string yields {}."""
        parser = ApexTimingWebSocketParser()
        assert parser.parse_websocket_message("") == {}

    def test_single_part_message_returns_empty_dict(self):
        """A message with no pipe separator yields {}."""
        parser = ApexTimingWebSocketParser()
        assert parser.parse_websocket_message("loneword") == {}

    def test_message_with_extra_pipes_in_value(self):
        """Everything beyond the second pipe is captured in 'value'."""
        parser = ApexTimingWebSocketParser()
        result = parser.parse_websocket_message("init|grid|<table>|extra|stuff")
        assert result == {
            'command': 'init',
            'parameter': 'grid',
            'value': '<table>|extra|stuff',
        }

    def test_title_message(self):
        parser = ApexTimingWebSocketParser()
        result = parser.parse_websocket_message("title|Race Session")
        assert result == {
            'command': 'title',
            'parameter': 'Race Session',
            'value': '',
        }


# ---------------------------------------------------------------------------
# DATA_TYPE_MAP
# ---------------------------------------------------------------------------

class TestDataTypeMap:
    """Tests for the DATA_TYPE_MAP dictionary on the parser instance."""

    # Expected entries that map to a real field name
    EXPECTED_MAPPINGS = {
        'sta': 'Status',
        'rk':  'Position',
        'no':  'Kart',
        'dr':  'Team',
        'llp': 'Last Lap',
        'blp': 'Best Lap',
        'gap': 'Gap',
        'int': 'Interval',
        'otr': 'RunTime',
        'pit': 'Pit Stops',
        'tlp': 'Total Laps',
    }

    # Entries that are intentionally skipped (mapped to None)
    SKIPPED_KEYS = {'s1', 's2', 's3', 'grp'}

    def test_all_expected_mappings_present(self):
        """Every key in EXPECTED_MAPPINGS is present and correct."""
        parser = ApexTimingWebSocketParser()
        for key, expected in self.EXPECTED_MAPPINGS.items():
            assert key in parser.DATA_TYPE_MAP, (
                f"DATA_TYPE_MAP missing key '{key}'"
            )
            assert parser.DATA_TYPE_MAP[key] == expected, (
                f"DATA_TYPE_MAP['{key}'] = {parser.DATA_TYPE_MAP[key]!r}, "
                f"expected {expected!r}"
            )

    def test_sector_times_map_to_none(self):
        """s1, s2, s3 must map to None (skip sector times)."""
        parser = ApexTimingWebSocketParser()
        for key in ('s1', 's2', 's3'):
            assert key in parser.DATA_TYPE_MAP, (
                f"DATA_TYPE_MAP missing key '{key}'"
            )
            assert parser.DATA_TYPE_MAP[key] is None, (
                f"DATA_TYPE_MAP['{key}'] = {parser.DATA_TYPE_MAP[key]!r}, "
                f"expected None"
            )

    def test_group_maps_to_none(self):
        """grp must map to None (skip group)."""
        parser = ApexTimingWebSocketParser()
        assert 'grp' in parser.DATA_TYPE_MAP
        assert parser.DATA_TYPE_MAP['grp'] is None

    def test_no_unexpected_keys(self):
        """DATA_TYPE_MAP should contain only the documented keys."""
        parser = ApexTimingWebSocketParser()
        documented = set(self.EXPECTED_MAPPINGS.keys()) | self.SKIPPED_KEYS
        actual = set(parser.DATA_TYPE_MAP.keys())
        unexpected = actual - documented
        assert not unexpected, f"Unexpected keys in DATA_TYPE_MAP: {unexpected}"


# ---------------------------------------------------------------------------
# Time parsing helpers (from race_ui.py)
# ---------------------------------------------------------------------------

class TestParseTimeToSeconds:
    """Tests for parse_time_to_seconds and _safe_parse_time."""

    # --- parse_time_to_seconds -------------------------------------------------

    def test_mm_ss_sss_format(self):
        assert _parse_time_to_seconds("1:23.456") == pytest.approx(83.456)

    def test_seconds_only_format(self):
        assert _parse_time_to_seconds("59.123") == pytest.approx(59.123)

    def test_comma_decimal_separator(self):
        """Commas are tolerated as decimal separators (some Apex feeds emit them)."""
        assert _parse_time_to_seconds("1:23,456") == pytest.approx(83.456)
        assert _parse_time_to_seconds("59,123") == pytest.approx(59.123)

    def test_zero_time(self):
        assert _parse_time_to_seconds("0:00.000") == 0.0

    def test_large_minutes(self):
        assert _parse_time_to_seconds("10:00.000") == 600.0

    def test_empty_string_returns_inf(self):
        assert _parse_time_to_seconds("") == float('inf')

    def test_none_returns_inf(self):
        assert _parse_time_to_seconds(None) == float('inf')

    def test_malformed_raises_value_error(self):
        with pytest.raises(ValueError):
            _parse_time_to_seconds("not_a_time")

    def test_empty_with_spaces_raises(self):
        """Only a truly empty string returns inf; whitespace raises."""
        with pytest.raises(ValueError):
            _parse_time_to_seconds("   ")

    def test_triple_colon_raises(self):
        """Malformed times with extra colons raise ValueError."""
        with pytest.raises(ValueError):
            _parse_time_to_seconds("1:23:45")

    # --- _safe_parse_time -----------------------------------------------------

    def test_safe_parse_valid_time(self):
        assert _safe_parse_time("1:30.000") == 90.0

    def test_safe_parse_malformed_defaults_to_inf(self):
        assert _safe_parse_time("bad") == float('inf')

    def test_safe_parse_none_defaults_to_inf(self):
        assert _safe_parse_time(None) == float('inf')

    def test_safe_parse_custom_default(self):
        assert _safe_parse_time("garbage", default=-1.0) == -1.0

    def test_safe_parse_empty_string_defaults_to_inf(self):
        # parse_time_to_seconds returns inf for empty, so _safe_parse_time
        # returns that (not the default, because no exception is raised).
        assert _safe_parse_time("") == float('inf')


# ---------------------------------------------------------------------------
# process_init_message helper
# ---------------------------------------------------------------------------

class TestProcessInitMessage:
    """Tests for process_init_message column-map construction."""

    def test_grid_init_with_data_type_headers(self):
        """A full grid init with data-type attributes builds column_map."""
        parser = ApexTimingWebSocketParser()
        html = (
            "<table>"
            "<tr class='head'>"
            "<td data-type='rk'>Clt</td>"
            "<td data-type='no'>Kart</td>"
            "<td data-type='dr'>Equipe</td>"
            "<td data-type='llp'>Dernier</td>"
            "<td data-type='blp'>Meilleur</td>"
            "<td data-type='gap'>Ecart</td>"
            "<td data-type='pit'>Stands</td>"
            "</tr>"
            "</table>"
        )
        parser.process_init_message({
            'command': 'init',
            'parameter': 'grid',
            'value': html,
        })

        # column_map is built from header cells (0-based indices)
        assert parser.column_map[0] == 'Position'   # data-type='rk'
        assert parser.column_map[1] == 'Kart'        # data-type='no'
        assert parser.column_map[2] == 'Team'        # data-type='dr'
        assert parser.column_map[3] == 'Last Lap'    # data-type='llp'
        assert parser.column_map[4] == 'Best Lap'    # data-type='blp'
        assert parser.column_map[5] == 'Gap'         # data-type='gap'
        assert parser.column_map[6] == 'Pit Stops'   # data-type='pit'

    def test_grid_init_creates_empty_row_entries(self):
        """Grid init with data rows creates empty dict entries per row.

        NOTE: Due to a ``continue``-before-field-assignment bug in
        process_init_message (line 228 jumps over lines 230-246), the
        per-cell field values are *not* stored; only the row-level
        empty dicts are created.
        """
        parser = ApexTimingWebSocketParser()
        html = (
            "<table>"
            "<tr class='head'>"
            "<td data-type='rk'>Clt</td>"
            "<td data-type='no'>Kart</td>"
            "<td data-type='dr'>Equipe</td>"
            "</tr>"
            "<tr data-id='r1'>"
            "<td>1</td>"
            "<td>55</td>"
            "<td>Team A</td>"
            "</tr>"
            "<tr data-id='r2'>"
            "<td>2</td>"
            "<td>42</td>"
            "<td>Team B</td>"
            "</tr>"
            "</table>"
        )
        parser.process_init_message({
            'command': 'init',
            'parameter': 'grid',
            'value': html,
        })

        # Rows are registered as keys with empty dicts
        assert 'r1' in parser.grid_data
        assert 'r2' in parser.grid_data
        assert parser.grid_data['r1'] == {}
        assert parser.grid_data['r2'] == {}

    def test_grid_init_row_map_not_populated(self):
        """row_map is NOT populated from data rows due to dead-code bug.

        The ``continue`` on line 228 skips the row_map assignment on
        line 246, so row_map stays empty after process_init_message.
        """
        parser = ApexTimingWebSocketParser()
        html = (
            "<table>"
            "<tr class='head'>"
            "<td data-type='no'>Kart</td>"
            "</tr>"
            "<tr data-id='r1'><td>99</td></tr>"
            "</table>"
        )
        parser.process_init_message({
            'command': 'init',
            'parameter': 'grid',
            'value': html,
        })
        assert parser.row_map == {}

    def test_non_grid_parameter_is_ignored(self):
        """init messages with parameter != 'grid' don't alter column_map."""
        parser = ApexTimingWebSocketParser()
        cm_before = dict(parser.column_map)
        parser.process_init_message({
            'command': 'init',
            'parameter': 'title',
            'value': 'Some Title',
        })
        assert parser.column_map == cm_before
        assert parser.grid_data == {}
