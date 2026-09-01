"""Parse ephemeris text from MPC confirmation pages into structured data.

This module extracts ephemeris tables from raw MPC page text using position-based
column parsing with fallback strategies. The parser is designed to handle variations
in MPC page formatting and returns a dictionary mapping object provisional
designations to DataFrames containing ephemeris data for each time step.

Key challenges addressed:
- Column positions may vary between page updates
- Header rows may be inconsistent or repeated
- Data rows are identified by leading date patterns (YYYY format)
- Fallback parsing uses regex word-splitting for robustness
"""

import re

import pandas as pd


def parse_mpc_data(page_text):
    """Parse ephemeris text from an MPC confirmation page.

    Extracts ephemeris tables for each unconfirmed object using column-position
    parsing (with fallback to regex-based parsing if positions cannot be
    determined). Each object's ephemeris is stored as a DataFrame with columns:
    Date, UT, R.A. (J2000), Decl, Elong, V, Object Alt, Sun Alt, Motion min, Motion PA.

    The parser identifies:
    - Object sections by the marker "Get the observations or orbits."
    - Header lines containing column names (Date, UT, R.A., etc.)
    - Data rows starting with a year (e.g., "2026")
    - Visibility windows by combining Object Alt, Sun Alt, Date, and UT

    Args:
        page_text: Raw text from MPC page, as returned by fetch_mpc_data().

    Returns:
        dict: Maps provisional object designation (str) to pandas.DataFrame.
        Each DataFrame contains one row per ephemeris time step. Returns empty
        dict if page_text is None, empty, or no objects are found.

    Notes:
        - Column extraction assumes specific spacing in the MPC page layout.
        - Fallback parsing splits headers by 2+ whitespaces for robustness.
        - Data rows with incomplete or malformed fields are included; consumers
          should validate numeric columns (altitude, time) before use.
        - Empty or NaN fields in critical columns may cause downstream filtering
          to skip those rows.
    """
    if not page_text:
        return {}

    lines = page_text.split('\n')
    ephemeris_dict = {}
    i = 0
    n = len(lines)

    # Columns to extract and their alternative names for fallback
    target_cols = ['Date', 'UT', 'R.A. (J2000)', 'Decl.', 'Elong.', 'V', 'Motion', 'Object', 'Sun']
    alt_map = {
        'R.A. (J2000)': 'R.A.',
        'Decl.': 'Decl',
        'Elong.': 'Elong',
        'Motion': 'Motion',
        'Object': 'Object',
        'Sun': 'Sun'
    }

    while i < n:
        line = lines[i].strip()
        # Detect the start of a new object section
        if line.startswith('Get the observations or orbits.'):
            obj_name = lines[i-1].strip().split()[0] if i > 0 else None
            i += 1

            # Locate the header line with column names
            header_line = None
            header_idx = None
            while i < n:
                if 'Date' in lines[i] and 'UT' in lines[i] and 'R.A.' in lines[i]:
                    header_line = lines[i]
                    header_idx = i
                    break
                i += 1
            if header_line is None:
                continue

            # Extract column positions
            col_positions = {}
            header_str = header_line
            for col in target_cols:
                search = col
                if col == 'R.A. (J2000)':
                    search = 'R.A. (J2000)'
                pos = header_str.find(search)
                if pos == -1:
                    alt = alt_map.get(col, col)
                    pos = header_str.find(alt)
                if pos != -1:
                    col_positions[col] = pos

            # Fallback if not all essential columns are found
            required = ['Date', 'UT', 'R.A. (J2000)', 'Decl.', 'Elong.', 'V', 'Object', 'Sun']
            if not all(k in col_positions for k in required):
                # Fallback: split the header by 2+ spaces
                header_parts = re.split(r'\s{2,}', header_line.strip())
                col_positions_fb = {}
                start = 0
                for part in header_parts:
                    pos = header_line.find(part, start)
                    if pos != -1:
                        col_positions_fb[part.strip()] = pos
                        start = pos + len(part)
                for col in target_cols:
                    for header_part in col_positions_fb:
                        if col.lower() in header_part.lower() or header_part.lower() in col.lower():
                            col_positions[col] = col_positions_fb[header_part]
                            break

            # Parse data rows until the next section or end of file
            i = header_idx + 1
            while i < n and lines[i].strip() == '':
                i += 1

            data_rows = []
            while i < n:
                line_stripped = lines[i].strip()
                if line_stripped.startswith('...'):
                    i += 1
                    continue
                if line_stripped.startswith('Get the observations'):
                    break
                if line_stripped == '' or line_stripped.startswith('Date'):
                    i += 1
                    continue
                if re.match(r'^\d{4}', line_stripped):   
                    fields = {}
                    full_line = lines[i]
                    if col_positions:
                        max_pos = max(col_positions.values())
                        if len(full_line) < max_pos + 20:
                            full_line = full_line.ljust(max_pos + 20)
                        for col, pos in col_positions.items():
                            next_positions = [p for p in col_positions.values() if p > pos]
                            end = min(next_positions) if next_positions else len(full_line)
                            raw = full_line[pos:end].strip()
                            fields[col] = raw
                    else:
                        i += 1
                        continue

                    date = fields.get('Date', '').strip()
                    ut = fields.get('UT', '').strip().replace('*', '').strip()
                    ra = fields.get('R.A. (J2000)', '').strip()
                    decl = fields.get('Decl.', '').strip()
                    elong = fields.get('Elong.', '').strip()
                    v_mag = fields.get('V', '').strip()
                    motion = fields.get('Motion', '').strip()
                    mot_parts = motion.split()
                    mot_min = mot_parts[0] if mot_parts else ''
                    mot_pa = mot_parts[1] if len(mot_parts) > 1 else ''
                    obj_str = fields.get('Object', '').strip()
                    obj_parts = obj_str.split()
                    obj_alt = obj_parts[1] if len(obj_parts) > 1 else ''
                    sun_str = fields.get('Sun', '').strip()
                    sun_parts = sun_str.split()
                    sun_alt = sun_parts[0] if sun_parts else ''

                    row = [date, ut, ra, decl, elong, v_mag, obj_alt, sun_alt, mot_min, mot_pa]
                    data_rows.append(row)

                i += 1

            if data_rows and obj_name:
                column_names = [
                    "Date", "UT", "R.A. (J2000)", "Decl", "Elong", "V",
                    "Object Alt", "Sun Alt", "Motion min", "Motion PA"
                ]
                df = pd.DataFrame(data_rows, columns=column_names)
                ephemeris_dict[obj_name] = df

            continue

        i += 1

    return ephemeris_dict