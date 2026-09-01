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
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
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
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_driver(self):
        """Get or create the ChromeDriver instance.

        Returns:
            selenium.webdriver.Chrome: Configured WebDriver in headless mode.
        """
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
        if self._driver:
            self._driver.quit()
            self._driver = None


# --- URL and Data Retrieval Functions ---

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
    obj_type = obj_type.strip().upper()
    if obj_type == "NEOCP":
        return "https://minorplanetcenter.net/iau/NEO/toconfirm_tabular.html"
    elif obj_type == "PCCP":
        return "https://minorplanetcenter.net/iau/NEO/pccp_tabular.html"
    else:
        raise ValueError("obj_type must be 'NEOCP' or 'PCCP'")


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


def fetch_mpc_data(obj_type, obs_code, use_cache=USE_CACHE):
    """Fetch full ephemeris text for all objects at a specified observatory.

    Uses Selenium to navigate the MPC page, select 'All objects', enter the
    observatory code, and submit the form. Results are cached locally to
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
    """
    # Create cache directory if it doesn't exist
    if use_cache:
        os.makedirs(CACHE_DIR, exist_ok=True)
        cache_file = os.path.join(CACHE_DIR, f"ephem_{obj_type}_{obs_code}.pkl")
        if os.path.exists(cache_file):
            with open(cache_file, 'rb') as f:
                print(f"Loaded cached ephemeris for {obj_type} (obs {obs_code})")
                return pickle.load(f)

    url = _get_mpc_url(obj_type)
    print(f"Fetching ephemeris via Selenium for {obj_type.upper()} (obs: {obs_code})...")

    driver = MPCDriver().get_driver()
    try:
        driver.get(url)

        # Select "All objects"
        radio = WebDriverWait(driver, SELENIUM_PAGE_LOAD_WAIT).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='radio' and @name='W' and @value='a']"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", radio)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", radio)

        # Insert the observatory code
        obs_input = WebDriverWait(driver, SELENIUM_PAGE_LOAD_WAIT).until(
            EC.presence_of_element_located((By.XPATH, "//input[@name='obscode']"))
        )
        obs_input.clear()
        obs_input.send_keys(obs_code)

        # Submit the form
        submit = WebDriverWait(driver, SELENIUM_PAGE_LOAD_WAIT).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@type='submit']"))
        )
        driver.execute_script("arguments[0].click();", submit)

        # Wait for the page to load and check for specific text indicating no results
        WebDriverWait(driver, SELENIUM_PAGE_LOAD_WAIT).until(
            lambda d: "No observers have reported" in d.page_source or 
                      "Date" in d.page_source or 
                      "No results found" in d.page_source
        )
        time.sleep(1)  # small delay to ensure the page is fully loaded

        if "No observers have reported" in driver.page_source or "No results found" in driver.page_source:
            print("No ephemeris available for today.")
            return None

        body = driver.find_element(By.TAG_NAME, "body")
        text = body.text

        # Save in cache
        if use_cache and text:
            with open(cache_file, 'wb') as f:
                pickle.dump(text, f)
            print(f"Cached ephemeris to {cache_file}")

        return text

    except (TimeoutException, NoSuchElementException, StaleElementReferenceException) as e:
        print(f"Selenium error: {e}")
        return None