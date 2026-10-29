from __future__ import annotations

import pandas as pd

from .config import DEFAULT_ALT_MIN, DEFAULT_DUR_MIN, SUN_ALT_LIMIT


def _normalize_visibility_dataframe(df):
    """Prepare a parsed MPC DataFrame for visibility checks."""
    if df is None or df.empty:
        return pd.DataFrame()

    df_proc = df.copy()
    if 'Date' in df_proc.columns and 'UT' in df_proc.columns:
        date_values = pd.to_datetime(
            df_proc['Date'].astype(str).str.strip(),
            format='%Y %m %d',
            errors='coerce',
        )
        ut_values = df_proc['UT'].astype(str).str.strip().str.replace('*', '', regex=False)
        hour_only = ut_values.str.fullmatch(r'\d{1,2}')
        hhmm = ut_values.str.fullmatch(r'\d{3,4}')
        decimal_hour = ut_values.str.fullmatch(r'\d{1,2}\.\d+')
        time_offsets = pd.Series(pd.NaT, index=df_proc.index, dtype='timedelta64[ns]')

        whole_hours = pd.to_numeric(ut_values[hour_only], errors='coerce')
        valid_hours = whole_hours.between(0, 23)
        time_offsets.loc[whole_hours.index[valid_hours]] = pd.to_timedelta(
            whole_hours.loc[valid_hours],
            unit='h',
        )

        hhmm_values = ut_values[hhmm].str.zfill(4)
        hhmm_hours = pd.to_numeric(hhmm_values.str[:2], errors='coerce')
        hhmm_minutes = pd.to_numeric(hhmm_values.str[2:], errors='coerce')
        valid_hhmm = hhmm_hours.le(23) & hhmm_minutes.le(59)
        hhmm_index = hhmm_values.index[valid_hhmm]
        time_offsets.loc[hhmm_index] = pd.to_timedelta(
            hhmm_hours.loc[hhmm_index] * 60 + hhmm_minutes.loc[hhmm_index],
            unit='m',
        )

        fractional_hours = pd.to_numeric(ut_values[decimal_hour], errors='coerce')
        valid_fractional_hours = fractional_hours.ge(0) & fractional_hours.lt(24)
        fractional_index = fractional_hours.index[valid_fractional_hours]
        time_offsets.loc[fractional_index] = pd.to_timedelta(
            fractional_hours.loc[fractional_index],
            unit='h',
        )

        df_proc['Datetime_UTC'] = date_values + time_offsets
    else:
        df_proc['Datetime_UTC'] = pd.NaT

    if 'Object Alt' in df_proc.columns:
        df_proc['Object Alt'] = pd.to_numeric(df_proc['Object Alt'], errors='coerce')
    if 'Sun Alt' in df_proc.columns:
        df_proc['Sun Alt'] = pd.to_numeric(df_proc['Sun Alt'], errors='coerce')

    required = ['Datetime_UTC', 'R.A. (J2000)', 'Decl', 'V']
    if 'Object Alt' not in df_proc.columns:
        required.append('Object Alt')
    if 'Sun Alt' not in df_proc.columns:
        required.append('Sun Alt')

    df_proc = df_proc.dropna(subset=[col for col in required if col in df_proc.columns])
    return df_proc


def _filter_ephemerides_by_date(ephem_dict, reference_date):
    """Keep only MPC rows whose UTC calendar date matches ``reference_date``."""
    if reference_date is None:
        return ephem_dict

    timestamp = pd.Timestamp(reference_date)
    if pd.isna(timestamp):
        raise ValueError("reference_date must be a valid date or datetime")
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC")
    date_label = timestamp.strftime("%Y %m %d")

    selected = {}
    for object_name, dataframe in ephem_dict.items():
        if dataframe is None or dataframe.empty or "Date" not in dataframe.columns:
            continue
        matching_rows = dataframe.loc[
            dataframe["Date"].astype(str).str.strip() == date_label
        ].copy()
        if not matching_rows.empty:
            selected[object_name] = matching_rows
    return selected


def filter_visible_objects(
    ephem_dict,
    altitude_min=None,
    time_min_minutes=None,
    reference_date=None,
):
    """
    Filter visible objects by altitude and duration criteria.

    The logic keeps rows where the object is above the requested altitude and the
    Sun is below the configured twilight limit. It then identifies contiguous
    visibility windows separated by gaps larger than 2 hours and returns the best
    candidate for each object. This is a triage function for provisional MPC data
    and is intentionally conservative: it ranks apparent visibility, but does not
    certify that a newly discovered object has a reliable orbit or a successful
    observing plan.

    Args:
        ephem_dict: Dictionary mapping object names to pandas DataFrames with
            ephemeris data.
        altitude_min: Minimum object altitude in degrees.
        time_min_minutes: Minimum continuous visibility duration in minutes.
        reference_date: Optional UTC calendar date to include. Only MPC rows
            from this date are considered when provided.

    Returns:
        pandas.DataFrame with one row per visible object and columns:
        'Temp Desig', 'R.A.', 'Decl.', 'V', 'Visible_Minutes', 'Max_Alt',
        'Max_Alt_Time_UTC', 'Window_Start_UTC', 'Window_End_UTC'.
    """
    if altitude_min is None:
        altitude_min = DEFAULT_ALT_MIN
    if time_min_minutes is None:
        time_min_minutes = DEFAULT_DUR_MIN

    if not ephem_dict:
        return pd.DataFrame()

    ephem_dict = _filter_ephemerides_by_date(ephem_dict, reference_date)
    if not ephem_dict:
        return pd.DataFrame()

    summary = []
    for obj_name, df in ephem_dict.items():
        df_proc = _normalize_visibility_dataframe(df)
        if df_proc.empty:
            continue

        required = ['Datetime_UTC', 'Object Alt', 'Sun Alt', 'R.A. (J2000)', 'Decl', 'V']
        if not all(col in df_proc.columns for col in required):
            continue

        df_vis = df_proc[
            (df_proc['Object Alt'] >= altitude_min) & (df_proc['Sun Alt'] <= SUN_ALT_LIMIT)
        ].copy()
        if df_vis.empty:
            continue

        df_vis['Window_ID'] = (df_vis['Datetime_UTC'].diff() > pd.Timedelta(hours=2)).cumsum()
        grouped = df_vis.groupby('Window_ID').agg(
            start=('Datetime_UTC', 'min'),
            end=('Datetime_UTC', 'max'),
            max_alt=('Object Alt', 'max'),
            idx_max=('Object Alt', 'idxmax'),
            ra=('R.A. (J2000)', 'first'),
            decl=('Decl', 'first'),
            v=('V', 'first'),
        )
        grouped['duration_min'] = (grouped['end'] - grouped['start']).dt.total_seconds() / 60.0

        valid = grouped[grouped['duration_min'] >= time_min_minutes]
        if valid.empty:
            continue

        total_min = valid['duration_min'].sum()
        best_row = valid.loc[valid['max_alt'].idxmax()]
        best_idx = best_row['idx_max']

        summary.append({
            'Temp Desig': obj_name,
            'R.A.': best_row['ra'],
            'Decl.': best_row['decl'],
            'V': best_row['v'],
            'Visible_Minutes': int(total_min),
            'Max_Alt': round(best_row['max_alt'], 1),
            'Max_Alt_Time_UTC': df_vis.loc[best_idx, 'Datetime_UTC'],
            'Window_Start_UTC': best_row['start'],
            'Window_End_UTC': best_row['end'],
        })

    return pd.DataFrame(summary)
