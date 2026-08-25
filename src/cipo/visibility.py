from datetime import timedelta

from skyfield import almanac
from skyfield.api import load


def calculate_observation_windows(
    latitude, longitude, start_year, num_years
):
    ts = load.timescale()
    eph = load('de421.bsp')
    windows = []

    for year in range(start_year, start_year + num_years):
        t0 = ts.utc(year, 1, 1)
        t1 = ts.utc(year, 12, 31, 23, 59, 59)

        moon_phases = almanac.moon_phases(eph)
        event_times, phases = almanac.find_discrete(t0, t1, moon_phases)

        for ti, phase in zip(event_times, phases):
            if phase == 0:  # 0 represents New Moon
                new_moon_date = ti.utc_datetime()
                start = new_moon_date - timedelta(days=7)
                end = new_moon_date + timedelta(days=7)
                windows.append((start.date(), new_moon_date.date(), end.date()))

    return windows
