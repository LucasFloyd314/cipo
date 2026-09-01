from __future__ import annotations

import pandas as pd

from .config import DEFAULT_ALT_MIN, DEFAULT_DUR_MIN, SUN_ALT_LIMIT


def filter_visible_objects(ephem_dict, altitude_min=None, time_min_minutes=None):
    """
    Filter visible objects by altitude and duration criteria.

    Identifies visibility windows (gaps > 2 hours separate windows) and selects
    objects with at least ``time_min_minutes`` duration at or above
    ``altitude_min`` degrees during astronomical night (Sun below -18°).

    Args:
        ephem_dict: Dictionary mapping object names to pandas DataFrames with
            ephemeris data. Each DataFrame must contain:
            'Date', 'UT', 'Object Alt', 'Sun Alt', 'R.A. (J2000)', 'Decl', 'V'.
        altitude_min: Minimum object altitude in degrees. If None, uses
            DEFAULT_ALT_MIN from config.
        time_min_minutes: Minimum continuous visibility duration in minutes.
            If None, uses DEFAULT_DUR_MIN from config.

    Returns:
        pandas.DataFrame with one row per visible object and columns:
        'Temp Desig', 'R.A.', 'Decl.', 'V', 'Visible_Minutes', 'Max_Alt',
        'Max_Alt_Time_UTC'. Empty DataFrame if no objects meet criteria.
    """
    if altitude_min is None:
        altitude_min = DEFAULT_ALT_MIN
    if time_min_minutes is None:
        time_min_minutes = DEFAULT_DUR_MIN

    if not ephem_dict:
        return pd.DataFrame()

    summary = []

    for obj_name, df in ephem_dict.items():
        df_proc = df.copy()

        # clean and convert to datetime
        ut_clean = df_proc['UT'].astype(str).str.replace(r'[\s\.]', '', regex=True).str.zfill(4)
        df_proc['Datetime_UTC'] = pd.to_datetime(
            df_proc['Date'].astype(str) + ' ' + ut_clean,
            format='%Y %m %d %H%M',
            errors='coerce'
        )

        # convert altitude and sun altitude to numeric
        df_proc['Object Alt'] = pd.to_numeric(df_proc['Object Alt'], errors='coerce')
        df_proc['Sun Alt'] = pd.to_numeric(df_proc['Sun Alt'], errors='coerce')

        # Remove rows with NaN in critical columns
        df_proc = df_proc.dropna(subset=['Datetime_UTC', 'Object Alt', 'Sun Alt', 'R.A. (J2000)', 'Decl', 'V'])
        if df_proc.empty:
            continue

        # Filter rows based on altitude and sun altitude
        df_vis = df_proc[(df_proc['Object Alt'] >= altitude_min) & (df_proc['Sun Alt'] <= SUN_ALT_LIMIT)].copy()
        if df_vis.empty:
            continue

        # Identify visibility windows by checking gaps greater than 2 hours
        df_vis['Window_ID'] = (df_vis['Datetime_UTC'].diff() > pd.Timedelta(hours=2)).cumsum()

        # group by Window_ID to find start, end, max altitude, and duration
        grouped = df_vis.groupby('Window_ID').agg(
            start=('Datetime_UTC', 'min'),
            end=('Datetime_UTC', 'max'),
            max_alt=('Object Alt', 'max'),
            idx_max=('Object Alt', 'idxmax'),
            ra=('R.A. (J2000)', 'first'),
            decl=('Decl', 'first'),
            v=('V', 'first')
        )

        # Calculate duration in minutes
        grouped['duration_min'] = (grouped['end'] - grouped['start']).dt.total_seconds() / 60.0

        # Filter windows that meet the minimum duration requirement
        valid = grouped[grouped['duration_min'] >= time_min_minutes]
        if valid.empty:
            continue

        total_min = valid['duration_min'].sum()
        # Choose the window with the highest maximum altitude
        best_row = valid.loc[valid['max_alt'].idxmax()]
        best_idx = best_row['idx_max']

        summary.append({
            'Temp Desig': obj_name,
            'R.A.': best_row['ra'],
            'Decl.': best_row['decl'],
            'V': best_row['v'],
            'Visible_Minutes': int(total_min),
            'Max_Alt': round(best_row['max_alt'], 1),
            'Max_Alt_Time_UTC': df_vis.loc[best_idx, 'Datetime_UTC']
        })

    return pd.DataFrame(summary)