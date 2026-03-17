import requests
import json

field_level_m = 1539.24


metar_url = 'https://aviationweather.gov/api/data/metar?ids=KLMO&format=json'


metar_r = requests.get(metar_url)
metar_data = metar_r.json()[0]

altimeter_millibars = metar_data['altim']
altimeter_inhg = float(altimeter_millibars * 0.0295300)
station_pressure =  altimeter_inhg * ((288-0.0065 * field_level_m) / 288) ** 5.2561
station_pressure_mb = 33.8639 * station_pressure
temp_c = metar_data['temp']
dewpoint_c = metar_data['dewp']
temp_kelvin = temp_c + 273.15
vap_pressure = 6.11 * 10**((7.5*dewpoint_c) / (237.3 + dewpoint_c))
virtual_temp = temp_kelvin / (1 - (vap_pressure / station_pressure_mb) * (1 - 0.622))
virtual_temp_rakine = ((9/5) * (virtual_temp - 273.15) + 32) + 459.67

density_altitude = 145366 * (1 - ((17.326 * station_pressure) / virtual_temp_rakine)**0.235)


