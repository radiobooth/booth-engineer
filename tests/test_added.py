from radiobooth.sources.added import bulk_days, drop_bulk_dates


def tracks(*days_counts):
    out = []
    for day, n in days_counts:
        out += [{"id": f"{day}-{i}", "added_at": f"{day}T12:00:00Z"} for i in range(n)]
    return out


def test_initial_import_and_later_bursts_are_dropped_real_adds_kept():
    lib = tracks(
        ("2011-03-04", 9000),  # Plex set up: everything at once
        ("2011-03-05", 3000),  # scan ran past midnight
        ("2011-03-15", 40),  # still within the first two weeks
        ("2011-06-01", 12),  # a real add
        ("2016-08-20", 2500),  # library moved, Plex re-added it all
        ("2019-02-11", 150),  # a big but real day (under 2% of 14,702)
        ("2024-10-02", 1),
    )
    lib.append({"id": "no-date"})
    assert bulk_days(lib) == {"2011-03-04", "2011-03-05", "2011-03-15", "2016-08-20"}
    assert drop_bulk_dates(lib) == 14540
    kept = sorted({t["added_at"][:10] for t in lib if "added_at" in t})
    assert kept == ["2011-06-01", "2019-02-11", "2024-10-02"]


def test_no_dates_is_fine():
    assert drop_bulk_dates([{"id": "1"}]) == 0
