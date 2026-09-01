"""Observation window calculations based on lunar phases and ephemeris data.

This module provides tools to identify optimal observation windows based on
lunar phase cycles (particularly New Moon periods). The module uses the JPL
ephemeris (DE421) to compute precise lunar events.
"""

from datetime import timedelta

from skyfield import almanac
from skyfield.api import load


def calculate_observation_windows(
    latitude, longitude, start_year, num_years
):
    """Calculate observation windows around New Moon dates.

    Identifies New Moon events within the specified years and returns 14-day
    windows (7 days before and after each New Moon) suitable for dark-sky
    observing at the specified location.

    Args:
        latitude: Observer latitude in decimal degrees (positive = North).
        longitude: Observer longitude in decimal degrees (positive = East;
            note: MPC uses geocentric west-positive convention).
        start_year: First year to search for New Moon events.
        num_years: Number of years to search (starting from start_year).

    Returns:
        list of tuples: Each tuple contains (start_date, new_moon_date, end_date)
        as datetime.date objects, representing the 7-days-before to 7-days-after
        window for each New Moon in the range.

    Raises:
        FileNotFoundError: If de421.bsp ephemeris file cannot be located.
        Exception: If Skyfield fails to compute lunar phases.

    Notes:
        - Requires ephemeris file 'de421.bsp' (DE421 JPL ephemeris).
        - Lunar phase computation is geocentric; observer location is not used
          in phase calculations, only stored for reference.
        - Window dates are in UTC.
    """
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

