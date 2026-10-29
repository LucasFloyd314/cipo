"""Parse ephemeris text from MPC confirmation pages into structured data.

This parser is intentionally conservative: it extracts the object sections from
raw MPC ephemeris text and normalizes the fields into a pandas DataFrame so
visibility checks operate on explicit values instead of raw strings.
"""

import re
from datetime import date

import pandas as pd


def get_mpc_ephemeris_max_date(page_text):
    """Return the latest UTC calendar date present in MPC ephemerides."""
    if not page_text:
        return None

    dates = (
        date(int(year), int(month), int(day))
        for year, month, day in re.findall(r'(?m)^(\d{4})\s+(\d{2})\s+(\d{2})\b', page_text)
    )
    return max(dates, default=None)


def _first_numeric_token(value):
    """Return the first numeric token in a raw MPC field."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r'[-+]?\d+(?:\.\d+)?', text)
    if match is None:
        return None
    return match.group(0)


def _extract_column_positions(header_line, target_cols):
    """Get approximate column positions from a header line."""
    col_positions = {}
    aliases = {
        'R.A. (J2000)': ['R.A. (J2000)', 'R.A.'],
        'Decl.': ['Decl.', 'Decl'],
        'Elong.': ['Elong.', 'Elong'],
        'Motion': ['Motion', 'Motion min'],
        'Object': ['Object', 'Object Alt'],
        'Sun': ['Sun', 'Sun Alt'],
    }

    for column in target_cols:
        candidates = aliases.get(column, [column])
        for candidate in candidates:
            pos = header_line.find(candidate)
            if pos != -1:
                col_positions[column] = pos
                break

    required = ['Date', 'UT', 'R.A. (J2000)', 'Decl.', 'Elong.', 'V', 'Object', 'Sun']
    if not all(column in col_positions for column in required):
        parts = re.split(r'\s{2,}', header_line.strip())
        offsets = {}
        start = 0
        for part in parts:
            pos = header_line.find(part, start)
            if pos != -1:
                offsets[part.strip()] = pos
                start = pos + len(part)
        for column in target_cols:
            for part, pos in offsets.items():
                if column.lower() in part.lower() or part.lower() in column.lower():
                    col_positions[column] = pos
                    break

    return col_positions


def parse_mpc_data(page_text):
    """Parse ephemeris text from an MPC confirmation page."""
    if not page_text:
        return {}

    lines = page_text.split('\n')
    ephemeris_dict = {}
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i].strip()
        if line.startswith('Get the observations or orbits.'):
            obj_name = lines[i - 1].strip().split()[0] if i > 0 else None
            i += 1

            header_idx = None
            while i < n:
                current = lines[i]
                if 'Date' in current and 'UT' in current and 'R.A.' in current:
                    header_idx = i
                    break
                i += 1
            if header_idx is None:
                continue

            i = header_idx + 1
            while i < n and (not lines[i].strip() or not re.match(r'^\d{4}\s+\d{2}\s+\d{2}', lines[i].strip())):
                i += 1

            data_rows = []
            while i < n:
                line_stripped = lines[i].strip()
                if not line_stripped:
                    i += 1
                    continue
                if line_stripped.startswith('...'):
                    i += 1
                    continue
                if line_stripped.startswith('Get the observations'):
                    break
                if not re.match(r'^\d{4}\s+\d{2}\s+\d{2}', line_stripped):
                    i += 1
                    continue

                tokens = line_stripped.split()
                if len(tokens) < 10:
                    i += 1
                    continue

                date = ' '.join(tokens[:3])
                ut = tokens[3].replace('*', '')

                if re.search(r':', tokens[4]) or len(tokens) < 16:
                    ra = tokens[4]
                    dec = tokens[5]
                    elong = tokens[6]
                    v_mag = tokens[7]
                    obj_alt = tokens[8] if len(tokens) > 8 else ''
                    sun_alt = tokens[9] if len(tokens) > 9 else ''
                    motion_min = ''
                    motion_pa = ''
                else:
                    ra = ' '.join(tokens[4:7])
                    dec = ' '.join(tokens[7:10])
                    elong = tokens[10]
                    v_mag = tokens[11]
                    motion_min = tokens[12]
                    motion_pa = tokens[13]
                    obj_alt = tokens[15] if len(tokens) > 15 else ''
                    sun_alt = tokens[16] if len(tokens) > 16 else ''

                row = [date, ut, ra, dec, elong, v_mag, obj_alt, sun_alt, motion_min, motion_pa]
                data_rows.append(row)
                i += 1

            if data_rows and obj_name:
                column_names = [
                    'Date', 'UT', 'R.A. (J2000)', 'Decl', 'Elong', 'V',
                    'Object Alt', 'Sun Alt', 'Motion min', 'Motion PA'
                ]
                df = pd.DataFrame(data_rows, columns=column_names)
                ephemeris_dict[obj_name] = df

            continue

        i += 1

    return ephemeris_dict