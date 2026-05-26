"""The fleet pace fingerprint relies on _segment_stints. Lock its behaviour:
pit-count increases split stints, the pit-in lap is dropped, and a 2x-median
ceiling removes stray slow laps."""


def _laps(triples):
    # _segment_stints wants (timestamp, lap_time_seconds, cumulative_pit_count)
    return [("t", secs, pit) for secs, pit in triples]


def test_pit_increase_splits_stints(fleet_app):
    laps = _laps([(60, 0), (60, 0), (60, 0), (61, 1), (61, 1), (61, 1)])
    stints = fleet_app._segment_stints(laps)
    assert len(stints) == 2


def test_pit_in_lap_dropped(fleet_app):
    # The first lap of stint 1 is a slow pit-in lap (200s) and must be excluded.
    laps = _laps([(60, 0), (60, 0), (60, 0), (200, 1), (61, 1), (62, 1)])
    stints = fleet_app._segment_stints(laps)
    second = stints[1]
    assert second["best"] == 61          # 200 dropped, fastest clean lap is 61
    assert second["mean"] == 61.5
    assert second["lap_count"] == 2


def test_ceiling_removes_stray_slow_lap(fleet_app):
    laps = _laps([(60, 0), (60, 0), (60, 0), (400, 0)])
    stints = fleet_app._segment_stints(laps)
    # clean = laps[1:] = [60, 60, 400]; median 60 -> ceiling 180 -> 400 removed
    assert stints[0]["best"] == 60
    assert stints[0]["mean"] == 60.0


def test_empty_input(fleet_app):
    assert fleet_app._segment_stints([]) == []
