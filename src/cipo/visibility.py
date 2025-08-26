from datetime import timedelta
from skyfield.api import load
from skyfield import almanac

def calcular_janelas_observacao(latitude, longitude, ano_inicial, n_anos):

    ts = load.timescale()
    eph = load('de421.bsp')  
    janelas = []

  
    for ano in range(ano_inicial, ano_inicial + n_anos):
        
        t0 = ts.utc(ano, 1, 1)
        t1 = ts.utc(ano, 12, 31, 23, 59, 59)
        

        fases_lua = almanac.moon_phases(eph)

        t_eventos, fases = almanac.find_discrete(t0, t1, fases_lua)
        

        for ti, fase in zip(t_eventos, fases):
            if fase == 0: 
                data_nova = ti.utc_datetime()
                inicio = data_nova - timedelta(days=7)
                fim = data_nova + timedelta(days=7)
                janelas.append((inicio.date(), data_nova.date(), fim.date()))
    
    return janelas

#traduzir para ingles