"""Observation-window utilities for lunar-cycle and site-specific dark-sky windows.

This module provides a conventional dark-sky search window around each new moon,
then extends it with a location-aware black-sky check using the observer's
latitude/longitude and the configured twilight threshold. The purpose is to
prioritize useful observing nights without over-claiming that a newly discovered
object has a definite, stable orbit.
"""

from datetime import timedelta

from skyfield import almanac
from skyfield.api import Topos, load


def _iter_new_moon_sequence(start_year, num_years):
    """Yield UTC datetimes for new moons in the requested calendar years.

    Args:
        start_year: First calendar year to search.
        num_years: Number of calendar years to include.
    """
    ts = load.timescale()
    eph = load('de421.bsp')
    for year in range(start_year, start_year + num_years):
        t0 = ts.utc(year, 1, 1)
        t1 = ts.utc(year, 12, 31, 23, 59, 59)
        event_times, phases = almanac.find_discrete(t0, t1, almanac.moon_phases(eph))
        for ti, phase in zip(event_times, phases):
            if phase == 0:
                yield ti.utc_datetime()


def calculate_oasi_observation_windows(start_year, num_years, date_format="%Y/%m/%d"):
    """Return 15-day calendar windows centered on each new moon for OASI.

    Returns dictionaries containing raw ``date`` objects and formatted display
    strings. Display dates use ``YYYY/MM/DD`` by default; ``date_format`` can
    override that presentation without changing the underlying date objects.

    Args:
        start_year: First calendar year to search.
        num_years: Number of calendar years to include.
        date_format: ``strftime`` format used for display labels.
    """
    windows = []
    for new_moon_dt in _iter_new_moon_sequence(start_year, num_years):
        start_date = (new_moon_dt - timedelta(days=7)).date()
        nm_date = new_moon_dt.date()
        end_date = (new_moon_dt + timedelta(days=7)).date()

        windows.append({
            "start_date": start_date,
            "new_moon_date": nm_date,
            "end_date": end_date,
            "display": f"{start_date.strftime(date_format)} to {end_date.strftime(date_format)}",
            "full_label": (
                f"{start_date.strftime(date_format)} until {end_date.strftime(date_format)} "
                f"[New Moon: {nm_date.strftime(date_format)}]"
            ),
        })
    return windows
def oasi_observation_windows(date, num_windows=2, date_format="%Y/%m/%d"):
    """Return upcoming OASI windows with consistently formatted date labels.

    Args:
        date: Reference calendar date; windows ending before this date are
            excluded.
        num_windows: Maximum number of upcoming windows to return.
        date_format: ``strftime`` format for the returned display labels.

    Returns:
        A list of window dictionaries, with dates formatted as ``YYYY/MM/DD``
        by default.
    """
    windows = calculate_oasi_observation_windows(
        date.year,
        1,
        date_format=date_format,
    )
    future_windows = [window for window in windows if window['end_date'] >= date]
    return future_windows[:num_windows]

def calculate_observation_windows(latitude, longitude, start_year, num_years):
    """Return site-specific new-moon dark windows using astronomical twilight.

    This compatibility helper uses a solar-altitude threshold of -18 degrees.

    Args:
        latitude: Observer latitude in degrees.
        longitude: Observer longitude in degrees, west negative.
        start_year: First calendar year to search.
        num_years: Number of calendar years to include.

    Returns:
        Tuples of ``(start_date, new_moon_date, end_date)`` for each window.
    """
    return calculate_site_observation_windows(
        latitude=latitude,
        longitude=longitude,
        start_year=start_year,
        num_years=num_years,
        twilight_alt=-18,
    )


def calculate_site_observation_windows(
    latitude,
    longitude,
    start_year,
    num_years,
    twilight_alt=-18,
    step_minutes=60,
):
    """Compute dark-sky windows around each new moon for a given site.

    The function returns a list of ``(start_date, new_moon_date, end_date)``
    tuples. Each tuple identifies the darkest interval around the new moon,
    bounded by local astronomical twilight using the observer's latitude and
    longitude.

    Args:
        latitude: Observer latitude in degrees.
        longitude: Observer longitude in degrees, using the usual geodetic
            sign convention where west is negative.
        start_year: First year to search.
        num_years: Number of years to include.
        twilight_alt: Sun altitude threshold for civil/astronomical darkness.
        step_minutes: Time step used to sample local dark-sky windows.

    Returns:
        list[tuple[datetime.date, datetime.date, datetime.date]]
    """
    ts = load.timescale()
    eph = load('de421.bsp')
    site = Topos(latitude_degrees=latitude, longitude_degrees=longitude)
    windows = []

    for new_moon_dt in _iter_new_moon_sequence(start_year, num_years):
        start_dt = new_moon_dt - timedelta(days=7)
        end_dt = new_moon_dt + timedelta(days=7)

        dark_start = None
        dark_end = None
        current_start = None
        current_end = None

        current = start_dt
        while current <= end_dt:
            utc_time = ts.utc(current.year, current.month, current.day, current.hour)
            observer = (eph['earth'] + site).at(utc_time)
            sun_alt = observer.observe(eph['sun']).apparent().altaz()[0].degrees
            if sun_alt <= twilight_alt:
                if current_start is None:
                    current_start = current
                current_end = current
            elif current_start is not None:
                if dark_start is None or (current_end - current_start) > (dark_end - dark_start):
                    dark_start = current_start
                    dark_end = current_end
                current_start = None
                current_end = None
            current += timedelta(minutes=step_minutes)

        if current_start is not None and (
            dark_start is None or (current_end - current_start) > (dark_end - dark_start)
        ):
            dark_start = current_start
            dark_end = current_end

        if dark_start is None:
            dark_start = start_dt
            dark_end = end_dt

        windows.append((dark_start.date(), new_moon_dt.date(), dark_end.date()))

    return windows
