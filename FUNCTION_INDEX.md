# CIPO Function Index

This index covers every function and method defined in `src/cipo` and the
maintained notebooks, including internal helpers. Entries are alphabetized by
function or method name.

| Function or method | Module | Summary |
| --- | --- | --- |
| `__new__` (`MPCDriver`) | `downloader.py` | Creates the singleton driver manager on its first instantiation. |
| `_calculate_altitudes_astropy` | `graphics.py` | Computes topocentric object altitudes with Astropy for a sequence of UTC times. |
| `_compute_night_bounds` | `graphics.py` | Finds the UTC interval during which the Sun is below the astronomical-twilight limit. |
| `_download_mpc_table` | `downloader.py` | Downloads and parses the MPC confirmation-page summary table. |
| `_extract_column_positions` | `parser.py` | Estimates fixed-width column positions from an MPC ephemeris header. |
| `_extract_constant_coordinates` | `main.py` | Converts the first MPC right-ascension and declination values to decimal degrees. |
| `_filter_ephemerides_by_date` | `filter.py` | Retains only ephemeris rows for the requested UTC calendar date. |
| `_filter_objects_by_visibility` | `graphics.py` | Selects plotted objects that meet altitude and duration limits. |
| `_first_numeric_token` | `parser.py` | Extracts the first numeric value from an MPC text field. |
| `_generate_summary` | `graphics.py` | Builds a summary table for objects selected for plotting. |
| `_get_mpc_url` | `downloader.py` | Returns the MPC confirmation-page URL for NEOCP or PCCP. |
| `_iter_new_moon_sequence` | `visibility.py` | Yields UTC timestamps for new moons across the requested years. |
| `_normalize_visibility_dataframe` | `filter.py` | Parses and validates date, time, altitude, and numeric visibility fields. |
| `_overlay_sun_moon` | `graphics.py` | Adds Sun and Moon altitude curves to a visibility plot. |
| `_plot_altitudes` | `graphics.py` | Creates the object-altitude chart and its visibility annotations. |
| `_validate_observatory_ephemeris` | `downloader.py` | Rejects MPC responses that are geocentric or rejected for the requested observatory. |
| `analyze_ephemeris_objects` | `main.py` | Fetches, parses, filters, and optionally plots MPC ephemerides. |
| `calculate_oasi_observation_windows` | `visibility.py` | Calculates 15-day calendar windows centered on new moons for OASI. |
| `calculate_observation_windows` | `visibility.py` | Calculates site-specific dark-sky windows around new moons. |
| `calculate_site_observation_windows` | `visibility.py` | Computes astronomical-night and new-moon windows for a specified site. |
| `dms_to_degrees` | `graphics.py` | Converts a sexagesimal declination string to decimal degrees. |
| `fetch_mpc_data` | `downloader.py` | Retrieves full MPC ephemerides for an observatory and object-page type. |
| `filter_dynamic_ephemerides` | `notebooks/visibility_test.ipynb` | Filters ephemeris rows by Brazil-time interval, altitude, astronomical night, and continuous visibility duration. |
| `filter_visible_objects` | `filter.py` | Filters candidate objects by altitude, darkness, duration, and optional date. |
| `get_driver` (`MPCDriver`) | `downloader.py` | Gets or creates the shared headless ChromeDriver instance. |
| `get_mpc_ephemeris_max_date` | `parser.py` | Finds the latest UTC date present in raw MPC ephemeris text. |
| `get_mpc_ephemeris_max_date_for_observatory` | `main.py` | Fetches ephemerides and returns their latest date for an observatory. |
| `get_object_ephemeris` | `graphics.py` | Retrieves one object's complete MPC ephemeris and optionally filters it by UTC date. |
| `get_oasi_observation_windows` | `main.py` | Returns upcoming OASI windows limited by the dates available from MPC. |
| `get_prioritized_observable_objects` | `main.py` | Returns candidates meeting the visibility, magnitude, and altitude limits, ranked by altitude, brightness, and duration. |
| `hms_to_degrees` | `graphics.py` | Converts a sexagesimal right-ascension string to decimal degrees. |
| `oasi_observation_windows` | `visibility.py` | Returns upcoming OASI windows with formatted date labels. |
| `parse_mpc_data` | `parser.py` | Parses MPC ephemeris text into a mapping of object designations to dataframes. |
| `plot_object_altitude` | `graphics.py` | Plots one object's MPC altitude curve, Moon altitude, Sun altitude, night interval, sunrise, and sunset for OASI. |
| `plot_visibility_from_mpc` | `graphics.py` | Plots unconfirmed-object altitude curves with optional Sun and Moon overlays. |
| `process_mpc_data` | `main.py` | Runs visibility analysis for a UTC date and can optionally prompt for object details. |
| `quit` (`MPCDriver`) | `downloader.py` | Closes the managed ChromeDriver session. |
