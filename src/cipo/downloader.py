"""Download and parse unconfirmed object data from the Minor Planet Center.

This module provides tools to fetch ephemeris tables from the MPC's NEOCP and
PCCP pages using Selenium for JavaScript rendering, with optional caching to
reduce network load and improve performance.

The ephemeris text is returned as raw page content and must be parsed by
parser.py to extract structured data.
"""

import io
import os
import pickle
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from .config import (
    CACHE_DIR,
    HEADERS,
    REQUESTS_TIMEOUT,
    SELENIUM_IMPLICIT_WAIT,
    SELENIUM_PAGE_LOAD_WAIT,
    USE_CACHE,
)

# --- ChromeDriver Singleton ---

class MPCDriver:
    """Singleton manager for ChromeDriver instances.

    Ensures only one browser instance is created and reused across the session,
    reducing memory overhead and improving performance when multiple downloads
    are needed. The driver is configured for headless operation.
    """
    _instance = None
    _driver = None

    def __new__(cls):
        """Create the singleton driver manager on its first instantiation."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_driver(self):
        """Get or create the ChromeDriver instance.

        Returns:
            selenium.webdriver.Chrome: Configured WebDriver in headless mode.
        """
        if self._driver is not None:
            try:
                self._driver.current_url
            except WebDriverException:
                self.quit()

        if self._driver is None:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
            self._driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=chrome_options
            )
            self._driver.implicitly_wait(SELENIUM_IMPLICIT_WAIT)
        return self._driver

    def quit(self):
        """Terminate the ChromeDriver instance."""
        driver, self._driver = self._driver, None
        if driver:
            try:
                driver.quit()
            except WebDriverException:
                pass


# --- URL and Data Retrieval Functions ---

def _normalize_obj_type(obj_type):
    """Return a validated uppercase MPC confirmation page identifier."""
    normalized = str(obj_type).strip().upper()
    if normalized not in {"NEOCP", "PCCP"}:
        raise ValueError("obj_type must be 'NEOCP' or 'PCCP'")
    return normalized


def _get_mpc_url(obj_type):
    """Return the appropriate MPC confirmation page URL.

    Args:
        obj_type: Either 'NEOCP' (NEO Confirmation Page) or 'PCCP'
            (Possible Comet Confirmation Page). Case-insensitive.

    Returns:
        str: Full URL to the MPC confirmation page.

    Raises:
        ValueError: If obj_type is neither 'NEOCP' nor 'PCCP'.
    """
    obj_type = _normalize_obj_type(obj_type)
    if obj_type == "NEOCP":
        return "https://minorplanetcenter.net/iau/NEO/toconfirm_tabular.html"
    return "https://minorplanetcenter.net/iau/NEO/pccp_tabular.html"


def _download_mpc_table(obj_type):
    """Download the preview summary table from an MPC confirmation page.

    Fetches the HTML table of unconfirmed objects from the specified MPC page,
    cleans hidden elements and checkboxes, and returns a parsed DataFrame.

    Args:
        obj_type: Either 'NEOCP' or 'PCCP'.

    Returns:
        pandas.DataFrame with columns: 'Temp Desig', 'Score', 'Discovery',
        'R.A.', 'Decl.', 'V', 'Updated', 'Note', 'NObs', 'Arc', 'H',
        'Not_Seen_dys'; or None if download/parsing fails.

    Side effects:
        Prints error messages to stdout on failure.
    """
    url = _get_mpc_url(obj_type)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUESTS_TIMEOUT)
        resp.raise_for_status()
    except (requests.RequestException, requests.Timeout) as e:
        print(f"Download error: {e}")
        return None

    soup = BeautifulSoup(resp.content, 'lxml')  # faster than 'html.parser'
    table = soup.find('table', {'class': 'tablesorter'})
    if not table:
        print("Table not found on the page.")
        return None

    # Remove hidden elements and checkboxes to clean the table
    for hidden in table.find_all('span', style=lambda x: x and 'display:none' in x):
        hidden.decompose()
    for chk in table.find_all('input'):
        chk.decompose()

    try:
        df_list = pd.read_html(io.StringIO(str(table)), flavor='bs4', header=0)
        if not df_list:
            return None
        df = df_list[0]
    except (ValueError, TypeError, KeyError) as e:
        print(f"Error in read_html: {e}")
        return None

    df = df.dropna(axis=1, how='all')
    df.columns = [str(col).strip() for col in df.columns]

    expected_cols = [
        'Temp Desig', 'Score', 'Discovery', 'R.A.', 'Decl.', 'V',
        'Updated', 'Note', 'NObs', 'Arc', 'H', 'Not_Seen_dys'
    ]

    if len(df.columns) == len(expected_cols):
        df.columns = expected_cols
    elif len(df.columns) > len(expected_cols):
        df = df.iloc[:, :len(expected_cols)]
        df.columns = expected_cols

    for col in ['Score', 'V', 'NObs', 'Arc', 'H', 'Not_Seen_dys']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    if 'Temp Desig' in df.columns:
        df = df[df['Temp Desig'].notna() & (df['Temp Desig'] != '')]

    return df.reset_index(drop=True)


def _validate_observatory_ephemeris(text, obs_code):
    """Reject MPC responses that are not specific to the requested observatory."""
    normalized_text = text.casefold()
    if "code is not in use" in normalized_text:
        raise ValueError(
            f"MPC rejected observatory code {obs_code!r}. "
            "Use an active MPC code; OASI's registered code is Y28."
        )
    if "ephemerides are for the geocenter" in normalized_text:
        raise ValueError(
            f"MPC returned geocentric ephemerides for {obs_code!r}, "
            "not ephemerides for the observatory. Check the MPC response."
        )


def fetch_mpc_data(obj_type, obs_code, use_cache=USE_CACHE):
    """Fetch full ephemeris text for all objects at a specified observatory.

    Uses Selenium to navigate the MPC page, select every object checkbox from
    that specific confirmation page, enter the observatory code, and submit the
    form. This avoids the shared CGI endpoint defaulting to NEOCP for an 'All
    objects' submission. Results are cached locally to
    reduce network traffic. Cached data is retrieved by object type and
    observatory code.

    Args:
        obj_type: Either 'NEOCP' or 'PCCP'.
        obs_code: Three-character MPC observatory code (e.g., 'Y28' for OASI).
        use_cache: If True (default), cache results to disk and reuse if available.

    Returns:
        str: Full page text containing ephemeris tables; None if request fails
        or no ephemeris data is available for the observatory.

    Side effects:
        Launches and controls a Chrome browser (headless). Creates cache directory
        if it does not exist. Prints status and error messages to stdout.

    Raises:
        ValueError: If the MPC rejects the observatory code or returns
            geocentric rather than observatory-specific ephemerides.
    """
    obs_code = obs_code.strip().upper()
    obj_type = _normalize_obj_type(obj_type)

    # Create cache directory if it doesn't exist
    if use_cache:
        os.makedirs(CACHE_DIR, exist_ok=True)
        cache_file = os.path.join(CACHE_DIR, f"ephem_v2_{obj_type}_{obs_code}.pkl")
        if os.path.exists(cache_file):
            with open(cache_file, 'rb') as f:
                cached_text = pickle.load(f)
                _validate_observatory_ephemeris(cached_text, obs_code)
                print(f"Loaded cached ephemeris for {obj_type} (obs {obs_code})")
                return cached_text

    url = _get_mpc_url(obj_type)
    print(f"Fetching ephemeris via Selenium for {obj_type.upper()} (obs: {obs_code})...")

    driver_manager = MPCDriver()
    for attempt in range(2):
        driver = driver_manager.get_driver()
        try:
            driver.get(url)

            # Scope every interaction to the ephemeris form.  Both confirmation
            # pages also contain a search form whose submit element is matched by
            # a generic input[type='submit'] XPath.
            ephemeris_form = "//input[@name='obscode']/ancestor::form[1]"

            radio = WebDriverWait(driver, SELENIUM_PAGE_LOAD_WAIT).until(
                EC.presence_of_element_located((
                    By.XPATH,
                    f"{ephemeris_form}//input[@type='radio' and @name='W' and @value='j']",
                ))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", radio)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", radio)

            # Selecting the objects explicitly is required because 'All objects'
            # is not page-specific at the shared confirmation CGI endpoint.
            object_checkboxes = driver.find_elements(
                By.XPATH,
                f"{ephemeris_form}//input[@type='checkbox' and @name='obj']",
            )
            try:
                object_checkboxes = list(object_checkboxes)
            except TypeError:
                object_checkboxes = []
            for checkbox in object_checkboxes:
                if not checkbox.is_selected():
                    driver.execute_script("arguments[0].click();", checkbox)

            obs_input = WebDriverWait(driver, SELENIUM_PAGE_LOAD_WAIT).until(
                EC.presence_of_element_located((
                    By.XPATH,
                    f"{ephemeris_form}//input[@name='obscode']",
                ))
            )
            obs_input.clear()
            obs_input.send_keys(obs_code)

            submit = WebDriverWait(driver, SELENIUM_PAGE_LOAD_WAIT).until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    f"{ephemeris_form}//input[@type='submit' and contains(normalize-space(@value), 'Get ephemerides')]",
                ))
            )
            driver.execute_script("arguments[0].click();", submit)

            WebDriverWait(driver, SELENIUM_PAGE_LOAD_WAIT).until(
                lambda current_driver: (
                    "No observers have reported" in current_driver.page_source
                    or "Date" in current_driver.page_source
                    or "No results found" in current_driver.page_source
                )
            )
            time.sleep(1)

            if (
                "No observers have reported" in driver.page_source
                or "No results found" in driver.page_source
            ):
                print("No ephemeris available for today.")
                return None

            text = driver.find_element(By.TAG_NAME, "body").text
            _validate_observatory_ephemeris(text, obs_code)

            if use_cache and text:
                with open(cache_file, 'wb') as f:
                    pickle.dump(text, f)
                print(f"Cached ephemeris to {cache_file}")

            return text

        except InvalidSessionIdException as e:
            driver_manager.quit()
            if attempt == 1:
                print(f"Selenium session error after retry: {e}")
                return None
            print("Selenium session expired; retrying with a new browser session.")
        except (TimeoutException, NoSuchElementException, StaleElementReferenceException) as e:
            print(f"Selenium error: {e}")
            return None

    return None