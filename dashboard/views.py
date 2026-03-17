import math
import requests
from datetime import datetime, timezone
from django.shortcuts import render
from django.http import JsonResponse
from .models import DropZone, Aircraft, Spot


# Pressure levels queried from Open-Meteo. 450 hPa added to cover exit
# altitudes up to ~15k AGL at high-elevation DZs.
_PRESSURE_LEVELS = [850, 825, 800, 775, 750, 725, 700, 650, 600, 550, 500, 450]
_TARGET_AGL_FT   = [1000, 2000, 3000, 4000, 5000, 9000, 12000]  # winds table rows

# Freefall constants
_OPENING_ALT_AGL  = 4000   # ft AGL — deployment altitude
_FREEFALL_RATE    = 176    # ft/s  — ~120 mph terminal velocity (belly)


# ── Shared wind helpers ───────────────────────────────────────────────────────

def _fetch_level_winds(dz):
    """
    Fetch wind speed, direction, temperature, and geopotential height at each
    pressure level from Open-Meteo. Returns a list of dicts sorted by agl_ft.
    """
    variables = []
    for level in _PRESSURE_LEVELS:
        variables += [
            f'windspeed_{level}hPa',
            f'winddirection_{level}hPa',
            f'temperature_{level}hPa',
            f'geopotential_height_{level}hPa',
        ]

    params = {
        'latitude':        dz.latitude,
        'longitude':       dz.longitude,
        'hourly':          ','.join(variables),
        'wind_speed_unit': 'kn',
        'forecast_days':   1,
        'timezone':        'UTC',
    }

    r = requests.get('https://api.open-meteo.com/v1/forecast', params=params, timeout=10)
    data = r.json()
    hourly = data['hourly']
    times  = hourly['time']

    current_hour_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:00')
    idx = times.index(current_hour_str) if current_hour_str in times else 0

    level_points = []
    for level in _PRESSURE_LEVELS:
        gh_m = hourly[f'geopotential_height_{level}hPa'][idx]
        ws   = hourly[f'windspeed_{level}hPa'][idx]
        wd   = hourly[f'winddirection_{level}hPa'][idx]
        temp = hourly[f'temperature_{level}hPa'][idx]
        if None in (gh_m, ws, wd, temp):
            continue
        level_points.append({
            'agl_ft': gh_m * 3.28084 - dz.field_elevation,
            'ws':     ws,
            'wd':     wd,
            'temp_c': temp,
        })

    level_points.sort(key=lambda x: x['agl_ft'])
    return level_points


def _interp_wind(target_agl, level_points):
    """
    Linearly interpolate wind at target_agl from level_points.
    Uses u/v decomposition so direction wraps correctly across 0/360.
    Returns dict with keys: wd, ws, u, v (knots, eastward/northward), temp_c.
    """
    below = next((p for p in reversed(level_points) if p['agl_ft'] <= target_agl), None)
    above = next((p for p in level_points           if p['agl_ft'] >  target_agl), None)
    if below is None:
        below = above
    if above is None:
        above = below
    if below is above:
        t = 0.0
    else:
        t = (target_agl - below['agl_ft']) / (above['agl_ft'] - below['agl_ft'])

    def to_uv(ws, wd_deg):
        # Met convention: FROM direction. u=eastward, v=northward.
        # Wind FROM 270 blows east: u=+ws, v=0. Wind FROM 0 blows south: u=0, v=-ws.
        rad = math.radians(wd_deg)
        return -ws * math.sin(rad), -ws * math.cos(rad)

    u1, v1 = to_uv(below['ws'], below['wd'])
    u2, v2 = to_uv(above['ws'], above['wd'])
    u = u1 + t * (u2 - u1)
    v = v1 + t * (v2 - v1)

    return {
        'wd':     (math.degrees(math.atan2(-u, -v)) + 360) % 360,
        'ws':     math.sqrt(u ** 2 + v ** 2),
        'u':      u,    # knots, eastward
        'v':      v,    # knots, northward
        'temp_c': below['temp_c'] + t * (above['temp_c'] - below['temp_c']),
    }


# ── Views ─────────────────────────────────────────────────────────────────────

def index(request):
    dz = DropZone.objects.first()
    return render(request, 'dashboard/index.html', {'dz': dz})


def api_weather(request):
    dz = DropZone.objects.first()
    if not dz:
        return JsonResponse({'error': 'No dropzone configured'}, status=500)

    url = f'https://aviationweather.gov/api/data/metar?ids={dz.awos_station_id}&format=json'
    try:
        r = requests.get(url, timeout=10)
        data = r.json()[0]
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

    # Density altitude — field_elevation stored in feet MSL, convert to meters
    field_m = dz.field_elevation * 0.3048
    altim_mb = data['altim']
    altim_inhg = altim_mb * 0.0295300
    station_pressure = altim_inhg * ((288 - 0.0065 * field_m) / 288) ** 5.2561
    station_pressure_mb = 33.8639 * station_pressure
    temp_c = data['temp']
    dewp_c = data['dewp']
    temp_k = temp_c + 273.15
    vap_pressure = 6.11 * 10 ** ((7.5 * dewp_c) / (237.3 + dewp_c))
    virtual_temp_k = temp_k / (1 - (vap_pressure / station_pressure_mb) * (1 - 0.622))
    virtual_temp_r = ((9 / 5) * (virtual_temp_k - 273.15) + 32) + 459.67
    density_altitude = 145366 * (1 - ((17.326 * station_pressure) / virtual_temp_r) ** 0.235)

    wdir = data.get('wdir', 0)
    wspd = data.get('wspd', 0)
    wgst = data.get('wgst')
    wind_str = f'{int(wdir):03d}° @ {int(wspd)}kts'
    if wgst:
        wind_str += f' G{int(wgst)}kts'

    return JsonResponse({
        'raw':             data.get('rawOb', ''),
        'temp_c':          round(temp_c, 1),
        'temp_f':          round(temp_c * 9 / 5 + 32, 1),
        'dewpoint_c':      round(dewp_c, 1),
        'wind_dir':        int(wdir),
        'wind_speed':      int(wspd),
        'wind_str':        wind_str,
        'visibility':      data.get('visib', ''),
        'clouds':          data.get('clouds', ''),
        'altimeter_inhg':  round(altim_inhg, 2),
        'density_altitude': round(density_altitude),
    })


def api_aircraft(request):
    dz = DropZone.objects.first()
    if not dz or not dz.adsb_url:
        return JsonResponse([], safe=False)

    tracked = {a.icao_hex.lower(): a for a in Aircraft.objects.all()}

    try:
        r = requests.get(dz.adsb_url, timeout=5)
        data = r.json()
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

    result = []
    for ac in data.get('aircraft', []):
        hex_code = ac.get('hex', '').lower()
        if hex_code not in tracked or 'lat' not in ac or 'lon' not in ac:
            continue
        obj = tracked[hex_code]
        result.append({
            'hex':      hex_code,
            'name':     obj.name,
            'lat':      ac['lat'],
            'lon':      ac['lon'],
            'alt_baro': ac.get('alt_baro'),
            'track':    ac.get('track', 0),
            'gs':       ac.get('gs'),
        })

    return JsonResponse(result, safe=False)


def api_spot(request):
    dz = DropZone.objects.first()
    spot = Spot.objects.filter(active=True).order_by('-dt_set').first()

    if not spot or not dz:
        return JsonResponse({'active': False})

    dn = (spot.lat - dz.latitude) * 69.0
    de = (spot.lon - dz.longitude) * 69.0 * math.cos(math.radians(dz.latitude))

    h = math.radians(spot.heading)
    jr_e, jr_n = math.sin(h), math.cos(h)

    along = de * jr_e + dn * jr_n
    cross = de * jr_n - dn * jr_e

    def bearing_to_cardinal(b):
        return ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][round(b / 45) % 8]

    offset_bearing = (spot.heading + 90) % 360 if cross >= 0 else (spot.heading - 90 + 360) % 360
    prior_label    = 'prior' if along <= 0 else 'after'
    prior_bearing  = (spot.heading + 180) % 360 if along <= 0 else spot.heading

    return JsonResponse({
        'active':       True,
        'lat':          spot.lat,
        'lon':          spot.lon,
        'heading':      spot.heading,
        'exit_alt':     spot.exit_altitude,
        'notes':        spot.notes,
        'dt_set':       spot.dt_set.isoformat(),
        'offset_dist':  round(abs(cross), 2),
        'offset_dir':   bearing_to_cardinal(offset_bearing),
        'prior_dist':   round(abs(along), 2),
        'prior_dir':    bearing_to_cardinal(prior_bearing),
        'prior_label':  prior_label,
    })


def api_winds(request):
    dz = DropZone.objects.first()
    if not dz:
        return JsonResponse({'error': 'No dropzone configured'}, status=500)

    try:
        level_points = _fetch_level_winds(dz)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

    result = []
    for agl in _TARGET_AGL_FT:
        w = _interp_wind(agl, level_points)
        result.append({
            'agl_ft':     agl,
            'wind_dir':   round(w['wd']),
            'wind_speed': round(w['ws'], 1),
            'temp_c':     round(w['temp_c'], 1),
            'temp_f':     round(w['temp_c'] * 9 / 5 + 32, 1),
        })

    return JsonResponse({'winds': result})


def api_drift(request):
    dz   = DropZone.objects.first()
    spot = Spot.objects.filter(active=True).order_by('-dt_set').first()

    if not spot or not dz:
        return JsonResponse({'active': False})
    if not spot.exit_altitude or spot.exit_altitude <= _OPENING_ALT_AGL:
        return JsonResponse({'active': False})

    try:
        level_points = _fetch_level_winds(dz)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

    # Walk from opening altitude up to exit altitude in 1,000 ft layers.
    # At each layer, the jumper spends (layer_height / _FREEFALL_RATE) seconds
    # and drifts with the wind vector at that layer's midpoint.
    # u/v from _interp_wind are in knots (= nautical miles / hour).
    total_east_nm  = 0.0
    total_north_nm = 0.0

    layer_base = _OPENING_ALT_AGL
    while layer_base < spot.exit_altitude:
        layer_top    = min(layer_base + 1000, spot.exit_altitude)
        layer_height = layer_top - layer_base
        mid_alt      = layer_base + layer_height / 2

        w        = _interp_wind(mid_alt, level_points)
        time_hr  = (layer_height / _FREEFALL_RATE) / 3600  # seconds → hours

        total_east_nm  += w['u'] * time_hr
        total_north_nm += w['v'] * time_hr

        layer_base += 1000

    # Convert nautical miles → statute miles, then to lat/lon offset
    NM_TO_SM = 1.15078
    drift_east_sm  = total_east_nm  * NM_TO_SM
    drift_north_sm = total_north_nm * NM_TO_SM

    opening_lat = spot.lat + drift_north_sm / 69.0
    opening_lon = spot.lon + drift_east_sm / (69.0 * math.cos(math.radians(dz.latitude)))

    drift_dist = math.sqrt(drift_east_sm ** 2 + drift_north_sm ** 2)
    drift_dir  = (math.degrees(math.atan2(drift_east_sm, drift_north_sm)) + 360) % 360

    return JsonResponse({
        'active':     True,
        'lat':        opening_lat,
        'lon':        opening_lon,
        'heading':    spot.heading,
        'drift_dist': round(drift_dist, 2),
        'drift_dir':  round(drift_dir),
        'exit_alt':   spot.exit_altitude,
    })
