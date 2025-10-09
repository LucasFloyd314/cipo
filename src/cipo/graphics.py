import re
import time
import math
import pandas as pd
from datetime import datetime, timedelta, timezone
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import urllib.request

# --- FUNÇÃO DE BUSCA DE COORDENADAS ---

def get_observatory_coords(iau_code):
    """
    Busca as coordenadas de um observatório na lista oficial do MPC.
    """
    mpc_url = "https://www.minorplanetcenter.net/iau/lists/ObsCodes.html"
    if not isinstance(iau_code, str) or len(iau_code) != 3:
        print("Erro: O código IAU deve ser uma string de 3 caracteres.")
        return None
    try:
        print(f"Acessando a lista de observatórios do MPC para encontrar '{iau_code}'...")
        with urllib.request.urlopen(mpc_url) as response:
            html_content = response.read().decode('utf-8')
        match = re.search(f"^{re.escape(iau_code)}.*", html_content, re.MULTILINE)
        if not match:
            print(f"Erro: Código de observatório '{iau_code}' não encontrado.")
            return None
        parts = match.group(0).split(maxsplit=4)
        longitude_mpc = float(parts[1])
        cos_lat = float(parts[2])
        sin_lat = float(parts[3])
        latitude = math.degrees(math.atan2(sin_lat, cos_lat))
        longitude = longitude_mpc if longitude_mpc <= 180 else longitude_mpc - 360
        print(f"Coordenadas encontradas: Lat {latitude:.4f}, Lon {longitude:.4f}")
        return latitude, longitude
    except Exception as e:
        print(f"Ocorreu um erro durante a busca das coordenadas: {e}")
        return None

# --- FUNÇÕES DE COLETA E PROCESSAMENTO DE DADOS ---

def fetch_data(url, observatorio_code):
    print(f"Iniciando a busca de dados em {url} para o observatório {observatorio_code}...")
    chrome_options = Options()
    chrome_options.add_argument("--headless"); chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080"); chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, "//input[@type='radio' and @name='W' and @value='a']"))).click()
        obs_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//input[@name='obscode']")))
        obs_input.clear(); obs_input.send_keys(observatorio_code)
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//input[@type='submit']"))).click()
        time.sleep(5)
        if "No observers have reported any observations" in driver.page_source:
            print("Nenhum objeto encontrado para os critérios de hoje."); return None
        print("Dados de texto coletados com sucesso.")
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception as e:
        print(f"Ocorreu um erro durante a execução do Selenium: {e}"); return None
    finally:
        driver.quit()

def process_data(page_text):
    if not page_text: return {}
    lines = page_text.splitlines(); blocks = {}
    current_object, current_block = None, []
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if line_stripped and (i + 1 < len(lines)) and ("Get the observations" in lines[i+1]):
            if current_object: blocks[current_object] = current_block
            current_object, current_block = line_stripped, []
            continue
        if current_object and "Get the observations" not in line_stripped and line_stripped:
            current_block.append(line_stripped)
    if current_object: blocks[current_object] = current_block
    column_names = ["Date", "UT", "R.A. (J2000)", "Decl", "Elong", "V", 'Motion min', 'Motion PA', "Object Azi", "Object Alt", "Sun Alt", "Moon Phase", "Moon Dist", "Moon Alt"]
    dataframes = {}
    for obj, block_lines in blocks.items():
        rows = []
        for line in block_lines:
            if re.match(r'^\d{4}', line.strip()):
                tokens = line.split()
                if len(tokens) >= 20:
                    rows.append([" ".join(tokens[0:3]), tokens[3], " ".join(tokens[4:7]), " ".join(tokens[7:10]), tokens[10], tokens[11], tokens[12], tokens[13], tokens[14], tokens[15], tokens[16], tokens[17], tokens[18], tokens[19]])
        if rows: dataframes[obj] = pd.DataFrame(rows, columns=column_names)
    print(f"Texto processado. {len(dataframes)} DataFrames criados.")
    return dataframes

# --- FUNÇÕES DE CÁLCULO ASTRONÔMICO ---

def hms_para_graus(ra_str):
    try: h, m, s = map(float, ra_str.split()); return (h + m/60 + s/3600) * 15
    except: return None

def dms_para_graus(dec_str):
    try:
        sinal = -1 if dec_str.strip().startswith('-') else 1
        d, m, s = map(float, dec_str.replace('-', '').replace('+', '').split())
        return sinal * (abs(d) + m/60 + s/3600)
    except: return None

def calcular_tempo_sideral_local(utc_dt, lon_deg):
    jd = utc_dt.timestamp() / 86400.0 + 2440587.5; d = jd - 2451545.0
    gmst = 18.697374558 + 24.06570982441908 * d
    return (gmst + (lon_deg / 15)) % 24

def calcular_altitude(ra_deg, dec_deg, lat_deg, lon_deg, utc_dt):
    if ra_deg is None or dec_deg is None: return None
    lat_rad, dec_rad = math.radians(lat_deg), math.radians(dec_deg)
    lst_hours = calcular_tempo_sideral_local(utc_dt, lon_deg)
    ha_rad = math.radians((lst_hours - (ra_deg / 15)) * 15)
    sin_alt = (math.sin(dec_rad) * math.sin(lat_rad) + math.cos(dec_rad) * math.cos(lat_rad) * math.cos(ha_rad))
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))

def get_celestial_coords(body_name, jd):
    n = jd - 2451545.0
    eclob = 23.439 - 0.0000004 * n; eclob_rad = math.radians(eclob)
    if body_name == 'sun':
        L = (280.460 + 0.9856474 * n) % 360; g = math.radians((357.528 + 0.9856003 * n) % 360)
        eclon = L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g); eclat = 0
    elif body_name == 'moon':
        L = (218.32 + 13.176396 * n) % 360; M = (134.96 + 13.064993 * n) % 360
        F = (93.27 + 13.229350 * n) % 360
        eclon = L + 6.29 * math.sin(math.radians(M)); eclat = 5.13 * math.sin(math.radians(F))
    else: return None, None
    eclon_rad, eclat_rad = math.radians(eclon), math.radians(eclat)
    ra_rad = math.atan2(math.sin(eclon_rad) * math.cos(eclob_rad) - math.tan(eclat_rad) * math.sin(eclob_rad), math.cos(eclon_rad))
    dec_rad = math.asin(math.sin(eclat_rad) * math.cos(eclob_rad) + math.cos(eclat_rad) * math.sin(eclob_rad) * math.sin(eclon_rad))
    return math.degrees(ra_rad) % 360, math.degrees(dec_rad)

# --- FUNÇÕES DE ANÁLISE E PLOTAGEM ---

def calcular_altitudes_para_objetos(dataframes, data_obs, lat_deg, lon_deg):
    if not dataframes: return {}, []
    inicio_calculo_utc = datetime.strptime(f'{data_obs} 12:00:00', '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
    intervalo_de_tempo = [inicio_calculo_utc + timedelta(minutes=10 * i) for i in range(145)]
    resultados = {}
    for obj_nome, df_obj in dataframes.items():
        if not df_obj.empty:
            primeira_obs = df_obj.iloc[0]
            ra_g = hms_para_graus(primeira_obs['R.A. (J2000)']); dec_g = dms_para_graus(primeira_obs['Decl'])
            resultados[obj_nome] = [calcular_altitude(ra_g, dec_g, lat_deg, lon_deg, t) for t in intervalo_de_tempo]
    return resultados, intervalo_de_tempo

def filtrar_objetos_observaveis(resultados, alt_min, dur_min):
    resultados_filtrados = {}
    intervalos_necessarios = dur_min // 10
    print(f"\nFiltrando objetos: devem estar acima de {alt_min}° por pelo menos {dur_min} min.")
    for nome_obj, altitudes in resultados.items():
        consecutivos = 0
        for alt in altitudes:
            if alt is not None and alt >= alt_min: consecutivos += 1
            else: consecutivos = 0
            if consecutivos >= intervalos_necessarios:
                resultados_filtrados[nome_obj] = altitudes; break
    print(f"Resultado: {len(resultados_filtrados)} de {len(resultados)} objetos são observáveis.")
    return resultados_filtrados

def plotar_grafico_altitude(resultados, intervalo, config_obs, page_name, alt_min, dur_min):
    if not resultados:
        print("\nNenhum objeto para plotar após a filtragem."); return

    print("\nGerando gráfico de visibilidade...")
    fig, ax = plt.subplots(figsize=(17, 9))
    
    for nome_obj, altitudes in resultados.items():
        ax.plot(intervalo, altitudes, label=nome_obj, lw=2)

    jd_meia_noite = datetime.strptime(f'{config_obs["data"]} 00:00:00', '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp() / 86400.0 + 2440587.5
    sun_ra, sun_dec = get_celestial_coords('sun', jd_meia_noite)
    moon_ra, moon_dec = get_celestial_coords('moon', jd_meia_noite)
    
    altitudes_lua = [calcular_altitude(moon_ra, moon_dec, config_obs["lat"], config_obs["lon"], t) for t in intervalo]
    ax.plot(intervalo, altitudes_lua, label='Lua', color='black', linestyle='--', lw=1.5)

    sunset, sunrise = None, None
    for minute in range(0, 24 * 60, 5):
        current_time = intervalo[0] - timedelta(hours=12) + timedelta(minutes=minute)
        alt_now = calcular_altitude(sun_ra, sun_dec, config_obs["lat"], config_obs["lon"], current_time)
        alt_prev = calcular_altitude(sun_ra, sun_dec, config_obs["lat"], config_obs["lon"], current_time - timedelta(minutes=5))
        if alt_prev is not None and alt_prev > 0 and alt_now <= 0: sunset = current_time
        if alt_prev is not None and alt_prev < 0 and alt_now >= 0: sunrise = current_time
    
    if sunset and sunrise:
        if sunrise < sunset: sunrise += timedelta(days=1)
        ax.axvline(sunset, color='r', linestyle='--', label=f'Pôr do Sol ({sunset.strftime("%H:%M")})')
        ax.axvline(sunrise, color='orange', linestyle='--', label=f'Nascer do Sol ({sunrise.strftime("%H:%M")})')
        ax.axvspan(sunset, sunrise, alpha=0.1, color='gray')

    ax.set_ylim(0, 90); ax.set_ylabel('Altitude (graus)', fontsize=14)
    ax.set_xlabel(f'Horário (UTC) começando em {config_obs["data"]} 12:00', fontsize=14)
    ax.set_title(f'Visibilidade {page_name} (Objetos acima de {alt_min}° por {dur_min} min)', fontsize=16)
    ax.grid(True, linestyle=':', alpha=0.7); ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M')); ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    plt.tight_layout(rect=[0, 0, 0.88, 1])
    
    output_filename = f'grafico_visibilidade_{page_name.replace(" ", "_")}.png'
    plt.savefig(output_filename)
    print(f"Gráfico salvo como '{output_filename}'")
    plt.show()