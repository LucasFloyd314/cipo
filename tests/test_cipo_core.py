import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import PropertyMock, patch

import numpy as np
import pandas as pd
from selenium.common.exceptions import InvalidSessionIdException

from cipo.downloader import MPCDriver, fetch_mpc_data
from cipo.filter import filter_visible_objects
from cipo.graphics import get_object_ephemeris, plot_object_altitude
from cipo.main import (
    analyze_ephemeris_objects,
    get_oasi_observation_windows,
    get_prioritized_observable_objects,
    process_mpc_data,
)
from cipo.parser import get_mpc_ephemeris_max_date, parse_mpc_data
from cipo.visibility import (
    calculate_observation_windows,
    calculate_oasi_observation_windows,
    calculate_site_observation_windows,
    oasi_observation_windows,
)


SAMPLE_PAGE = '''
K26A02
Get the observations or orbits.
Date     UT       R.A. (J2000)   Decl.   Elong.   V   Object  Sun
2026 01 01  0000  10:00:00  +00:00  0  18.0  20  -20
2026 01 01  0010  10:00:00  +00:00  0  18.0  21  -20
2026 01 01  0020  10:00:00  +00:00  0  18.0  22  -20
2026 01 01  0030  10:00:00  +00:00  0  18.0  23  -20
2026 01 01  0040  10:00:00  +00:00  0  18.0  20  -20
'''


class CipoCoreTests(unittest.TestCase):
    def test_get_mpc_ephemeris_max_date(self):
        self.assertEqual(
            get_mpc_ephemeris_max_date(
                '2026 09 15 22 data\n2026 09 16 03 data\n'
            ),
            date(2026, 9, 16),
        )

    @patch('cipo.main.get_mpc_ephemeris_max_date_for_observatory', return_value=date(2026, 9, 25))
    def test_get_oasi_observation_windows_respects_mpc_max_date(self, _mock_max_date):
        windows = get_oasi_observation_windows(
            reference_date=date(2026, 9, 1),
            num_windows=2,
        )
        self.assertTrue(windows)
        self.assertTrue(all(window['end_date'] <= date(2026, 9, 25) for window in windows))

    def test_parse_mpc_data_extracts_rows(self):
        parsed = parse_mpc_data(SAMPLE_PAGE)
        self.assertIn('K26A02', parsed)
        df = parsed['K26A02']
        self.assertEqual(list(df.columns[:8]), ['Date', 'UT', 'R.A. (J2000)', 'Decl', 'Elong', 'V', 'Object Alt', 'Sun Alt'])
        self.assertEqual(len(df), 5)

    def test_parse_mpc_data_handles_real_neocp_row_format(self):
        raw = '''
00001sS
Get the observations or orbits.
Date       UT      R.A. (J2000) Decl.  Elong.  V        Motion     Object     Sun         Moon        Uncertainty
            h                                        "/min   P.A.  Azi. Alt.  Alt.  Phase Dist. Alt.
2026 09 15 22     23 23 14.4 +09 17 56 167.6  17.8    0.28  293.4  256  +23   -23    0.23  125  +31   Map/Offsets
'''
        parsed = parse_mpc_data(raw)
        self.assertIn('00001sS', parsed)
        df = parsed['00001sS']
        self.assertEqual(df['R.A. (J2000)'].iloc[0].strip(), '23 23 14.4')
        self.assertEqual(df['Decl'].iloc[0].strip(), '+09 17 56')

    def test_filter_visible_objects_uses_altitude_and_duration(self):
        ephem = {'K26A02': pd.DataFrame({
            'Date': ['2026 01 01'] * 5,
            'UT': ['0000', '0010', '0020', '0030', '0040'],
            'R.A. (J2000)': ['10:00:00'] * 5,
            'Decl': ['+00:00'] * 5,
            'Elong': ['0'] * 5,
            'V': ['18.0'] * 5,
            'Object Alt': ['20', '21', '22', '23', '20'],
            'Sun Alt': ['-20'] * 5,
            'Motion min': ['0.1'] * 5,
            'Motion PA': ['90'] * 5,
        })}
        result = filter_visible_objects(ephem, altitude_min=10, time_min_minutes=30)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]['Temp Desig'], 'K26A02')
        self.assertGreaterEqual(result.iloc[0]['Visible_Minutes'], 30)
        self.assertGreaterEqual(result.iloc[0]['Max_Alt'], 20)

    def test_filter_visible_objects_interprets_integer_ut_as_hours(self):
        ephem = {'K26A02': pd.DataFrame({
            'Date': ['2026 10 27'] * 4,
            'UT': ['20', '21', '22', '23'],
            'R.A. (J2000)': ['10 00 00'] * 4,
            'Decl': ['+00 00 00'] * 4,
            'Elong': ['0'] * 4,
            'V': ['19.2'] * 4,
            'Object Alt': ['28', '39', '49', '58'],
            'Sun Alt': ['-20', '-25', '-30', '-36'],
        })}

        result = filter_visible_objects(
            ephem,
            altitude_min=10,
            time_min_minutes=30,
            reference_date=date(2026, 10, 27),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]['Visible_Minutes'], 180)
        self.assertEqual(
            result.iloc[0]['Max_Alt_Time_UTC'],
            pd.Timestamp('2026-10-27 23:00:00'),
        )

    def test_filter_visible_objects_uses_only_reference_date(self):
        dates = ['2026 10 27'] * 4 + ['2026 10 28'] * 4
        ephem = {'K26A02': pd.DataFrame({
            'Date': dates,
            'UT': ['0000', '0010', '0020', '0030'] * 2,
            'R.A. (J2000)': ['10 00 00'] * 4 + ['11 00 00'] * 4,
            'Decl': ['+00 00 00'] * 4 + ['+10 00 00'] * 4,
            'Elong': ['0'] * 8,
            'V': ['18.5'] * 4 + ['20.1'] * 4,
            'Object Alt': ['20', '25', '30', '25', '40', '41', '42', '43'],
            'Sun Alt': ['-20'] * 8,
        })}

        result = filter_visible_objects(
            ephem,
            altitude_min=10,
            time_min_minutes=30,
            reference_date=date(2026, 10, 27),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]['V'], '18.5')
        self.assertEqual(result.iloc[0]['Max_Alt'], 30)
        self.assertEqual(
            result.iloc[0]['Max_Alt_Time_UTC'].date(),
            date(2026, 10, 27),
        )
        self.assertTrue(
            filter_visible_objects(
                ephem,
                altitude_min=10,
                time_min_minutes=30,
                reference_date=date(2026, 10, 29),
            ).empty
        )
        utc_reference_datetime = datetime(
            2026,
            10,
            27,
            23,
            30,
            tzinfo=timezone(timedelta(hours=-3)),
        )
        utc_result = filter_visible_objects(
            ephem,
            altitude_min=10,
            time_min_minutes=30,
            reference_date=utc_reference_datetime,
        )
        self.assertEqual(utc_result.iloc[0]['V'], '20.1')

    @patch('cipo.main.plot_visibility_from_mpc')
    @patch('cipo.main.fetch_mpc_data', return_value=SAMPLE_PAGE)
    def test_analysis_plots_only_the_requested_date(
        self,
        _mock_fetch,
        mock_plot,
    ):
        result = analyze_ephemeris_objects(
            plot=True,
            plot_all=True,
            print_visible=False,
            reference_date=date(2026, 1, 1),
        )

        self.assertEqual(len(result), 1)
        plotted_ephemerides = mock_plot.call_args.kwargs['ephem_dict']
        self.assertTrue(
            all(
                row_date == '2026 01 01'
                for dataframe in plotted_ephemerides.values()
                for row_date in dataframe['Date']
            )
        )

    @patch('cipo.main.analyze_ephemeris_objects')
    def test_get_prioritized_observable_objects_filters_and_sorts(self, mock_analyze):
        mock_analyze.return_value = pd.DataFrame({
            'Temp Desig': ['lower-alt', 'bright', 'too-faint', 'at-limit', 'max-mag'],
            'R.A.': ['10 00 00'] * 5,
            'Decl.': ['+00 00 00'] * 5,
            'V': ['15', '14', '19', '13', '18'],
            'Visible_Minutes': [90, 60, 90, 60, 120],
            'Max_Alt': [50, 60, 70, 10, 40],
            'Max_Alt_Time_UTC': pd.to_datetime(['2026-10-27'] * 5),
            'Window_Start_UTC': pd.to_datetime(['2026-10-27'] * 5),
            'Window_End_UTC': pd.to_datetime(['2026-10-27'] * 5),
        })

        result = get_prioritized_observable_objects(
            obs_code='Y28',
            obj_type='NEOCP',
            magnitude_max=18,
            altitude_min=10,
            duration_min=30,
            reference_date=date(2026, 10, 27),
        )

        self.assertEqual(
            result['Temp Desig'].tolist(),
            ['bright', 'lower-alt', 'max-mag'],
        )
        self.assertEqual(result['Prioridade'].tolist(), [1, 2, 3])
        mock_analyze.assert_called_once_with(
            obs_code='Y28',
            obj_type='NEOCP',
            altitude_min=10,
            duration_min=30,
            plot=False,
            print_visible=False,
            reference_date=date(2026, 10, 27),
        )

    @patch('cipo.main.analyze_ephemeris_objects', return_value=pd.DataFrame())
    def test_get_prioritized_observable_objects_returns_empty_priority_column(
        self,
        _mock_analyze,
    ):
        result = get_prioritized_observable_objects()

        self.assertTrue(result.empty)
        self.assertIn('Prioridade', result.columns)

    @patch('cipo.main.analyze_ephemeris_objects', return_value=pd.DataFrame())
    def test_process_mpc_data_forwards_date_and_plot_options(self, mock_analyze):
        reference_date = date(2026, 10, 27)

        process_mpc_data(
            interactive_mode=False,
            print_visible=False,
            reference_date=reference_date,
            plot=True,
        )

        mock_analyze.assert_called_once_with(
            obs_code='Y28',
            obj_type='NEOCP',
            altitude_min=10,
            duration_min=30,
            plot=True,
            print_visible=False,
            reference_date=reference_date,
        )

    @patch('cipo.main.analyze_ephemeris_objects', return_value=pd.DataFrame())
    @patch('cipo.main.pd.Timestamp.now')
    def test_process_mpc_data_defaults_to_current_utc_date(
        self,
        mock_now,
        mock_analyze,
    ):
        mock_now.return_value = pd.Timestamp('2026-10-27 16:00', tz='UTC')

        process_mpc_data(interactive_mode=False, print_visible=False)

        self.assertEqual(
            mock_analyze.call_args.kwargs['reference_date'],
            date(2026, 10, 27),
        )

    @patch('cipo.downloader.ChromeDriverManager.install', return_value='chromedriver')
    @patch('cipo.downloader.Service')
    @patch('cipo.downloader.Options')
    @patch('cipo.downloader.webdriver.Chrome')
    def test_mpc_driver_recreates_a_closed_session(
        self,
        mock_chrome,
        _mock_options,
        _mock_service,
        _mock_driver_path,
    ):
        manager = MPCDriver()
        previous_driver = manager._driver
        stale_driver = unittest.mock.Mock()
        type(stale_driver).current_url = PropertyMock(
            side_effect=InvalidSessionIdException('closed session')
        )
        replacement_driver = unittest.mock.Mock()
        manager._driver = stale_driver
        mock_chrome.return_value = replacement_driver

        try:
            self.assertIs(manager.get_driver(), replacement_driver)
        finally:
            manager._driver = previous_driver

        stale_driver.quit.assert_called_once()
        replacement_driver.implicitly_wait.assert_called_once()

    @patch('cipo.downloader.time.sleep')
    @patch('cipo.downloader.WebDriverWait')
    @patch('cipo.downloader.MPCDriver')
    def test_fetch_mpc_data_retries_when_session_expires(
        self,
        mock_driver_class,
        mock_wait_class,
        _mock_sleep,
    ):
        dead_driver = unittest.mock.Mock()
        dead_driver.get.side_effect = InvalidSessionIdException('closed session')
        working_driver = unittest.mock.Mock()
        working_driver.page_source = 'Date'
        working_driver.find_element.return_value.text = 'MPC ephemeris'

        manager = mock_driver_class.return_value
        manager.get_driver.side_effect = [dead_driver, working_driver]
        waiter = mock_wait_class.return_value
        waiter.until.side_effect = [
            unittest.mock.Mock(),
            unittest.mock.Mock(),
            unittest.mock.Mock(),
            True,
        ]

        result = fetch_mpc_data('NEOCP', 'Y28', use_cache=False)

        self.assertEqual(result, 'MPC ephemeris')
        self.assertEqual(manager.get_driver.call_count, 2)
        manager.quit.assert_called_once()

    def test_mpc_confirmation_urls_are_page_specific(self):
        from cipo.downloader import _get_mpc_url

        self.assertEqual(
            _get_mpc_url('NEOCP'),
            'https://minorplanetcenter.net/iau/NEO/toconfirm_tabular.html',
        )
        self.assertEqual(
            _get_mpc_url('PCCP'),
            'https://minorplanetcenter.net/iau/NEO/pccp_tabular.html',
        )
        with self.assertRaisesRegex(ValueError, 'obj_type must be'):
            _get_mpc_url('OTHER')

    @patch('cipo.downloader.time.sleep')
    @patch('cipo.downloader.WebDriverWait')
    @patch('cipo.downloader.MPCDriver')
    def test_fetch_mpc_data_normalizes_observatory_code_to_uppercase(
        self,
        mock_driver_class,
        mock_wait_class,
        _mock_sleep,
    ):
        driver = unittest.mock.Mock()
        driver.page_source = 'Date'
        driver.find_element.return_value.text = 'MPC ephemeris'
        mock_driver_class.return_value.get_driver.return_value = driver
        observatory_input = unittest.mock.Mock()
        mock_wait_class.return_value.until.side_effect = [
            unittest.mock.Mock(),
            observatory_input,
            unittest.mock.Mock(),
            True,
        ]

        result = fetch_mpc_data('NEOCP', 'y28', use_cache=False)

        self.assertEqual(result, 'MPC ephemeris')
        observatory_input.send_keys.assert_called_once_with('Y28')
        driver.find_element.assert_called_once()

    @patch('cipo.downloader.time.sleep')
    @patch('cipo.downloader.WebDriverWait')
    @patch('cipo.downloader.MPCDriver')
    def test_fetch_mpc_data_rejects_geocentric_ephemerides(
        self,
        mock_driver_class,
        mock_wait_class,
        _mock_sleep,
    ):
        driver = unittest.mock.Mock()
        driver.page_source = 'Date'
        driver.find_element.return_value.text = 'Ephemerides are for the geocenter.'
        mock_driver_class.return_value.get_driver.return_value = driver
        mock_wait_class.return_value.until.side_effect = [
            unittest.mock.Mock(),
            unittest.mock.Mock(),
            unittest.mock.Mock(),
            True,
        ]

        with self.assertRaisesRegex(ValueError, 'geocentric ephemerides'):
            fetch_mpc_data('NEOCP', 'y28', use_cache=False)

    def test_calculate_observation_windows_returns_new_moon_windows(self):
        windows = calculate_observation_windows(-22.5, -43.5, 2026, 1)
        self.assertTrue(len(windows) > 0)
        self.assertEqual(len(windows[0]), 3)

    def test_calculate_site_observation_windows_uses_local_site_geometry(self):
        windows = calculate_site_observation_windows(-22.5, -43.5, 2026, 1, twilight_alt=-18)
        self.assertTrue(len(windows) > 0)
        self.assertEqual(len(windows[0]), 3)

    def test_calculate_oasi_observation_windows_spans_15_days(self):
        window = calculate_oasi_observation_windows(2026, 1)[0]
        start_date = window['start_date']
        new_moon_date = window['new_moon_date']
        end_date = window['end_date']
        self.assertEqual((end_date - start_date).days, 14)
        self.assertEqual((new_moon_date - start_date).days, 7)
        self.assertEqual((end_date - new_moon_date).days, 7)

    @patch(
        'cipo.visibility._iter_new_moon_sequence',
        return_value=[datetime(2026, 3, 19)],
    )
    def test_oasi_window_labels_use_year_month_day_by_default(self, _mock_new_moons):
        windows = calculate_oasi_observation_windows(2026, 1)

        self.assertEqual(windows[0]['display'], '2026/03/12 to 2026/03/26')
        self.assertEqual(
            windows[0]['full_label'],
            '2026/03/12 until 2026/03/26 [New Moon: 2026/03/19]',
        )

    @patch(
        'cipo.visibility._iter_new_moon_sequence',
        return_value=[datetime(2026, 3, 19)],
    )
    def test_oasi_window_wrapper_preserves_custom_date_format(self, _mock_new_moons):
        result = oasi_observation_windows(
            date=date(2026, 3, 1),
            date_format='%Y-%m-%d',
        )

        self.assertEqual(result[0]['display'], '2026-03-12 to 2026-03-26')
        self.assertEqual(
            result[0]['full_label'],
            '2026-03-12 until 2026-03-26 [New Moon: 2026-03-19]',
        )

    @patch('cipo.graphics.fetch_mpc_data', return_value=SAMPLE_PAGE)
    def test_get_object_ephemeris_returns_one_object(self, _mock_fetch):
        result = get_object_ephemeris('K26A02', reference_date=date(2026, 1, 1))
        self.assertEqual(len(result), 5)
        self.assertTrue(all(result['Date'] == '2026 01 01'))

    @patch('cipo.graphics.fetch_mpc_data', return_value=SAMPLE_PAGE)
    def test_get_object_ephemeris_rejects_unknown_object(self, _mock_fetch):
        with self.assertRaises(KeyError):
            get_object_ephemeris('UNKNOWN')

    def test_plot_object_altitude_accepts_fixture_dataframe(self):
        dataframe = pd.DataFrame({
            'Date': ['2026 01 01'] * 5,
            'UT': ['1800', '1900', '2000', '2100', '2200'],
            'Object Alt': ['20', '30', '40', '30', '20'],
            'R.A. (J2000)': ['10 00 00', '10 30 00', '11 00 00', '11 30 00', '12 00 00'],
            'Decl': ['-20 00 00', '-15 00 00', '-10 00 00', '-05 00 00', '+00 00 00'],
        })

        class AltitudeResult:
            def __init__(self, values):
                self.alt = type('AltData', (), {'deg': values})()

        class Body:
            def transform_to(self, frame):
                length = len(frame.obstime)
                if self.sun:
                    values = 40.0 * np.cos(np.linspace(0, 2 * np.pi, length)) - 20.0
                else:
                    values = np.linspace(-30, 30, length)
                return AltitudeResult(values)

            def __init__(self, sun):
                self.sun = sun

        with patch('cipo.graphics.get_body', side_effect=[Body(True), Body(False)]), \
             patch('cipo.graphics.plt.show'):
            figure = plot_object_altitude(
                'K26A02',
                obs_code='Y28',
                reference_date=date(2026, 1, 1),
                ephemeris_dataframe=dataframe,
                step_minutes=10,
            )

        self.assertIsNotNone(figure)
        self.assertEqual(len(figure.axes), 1)


if __name__ == '__main__':
    unittest.main()
