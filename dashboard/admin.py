from django.contrib import admin
from .models import DropZone, Aircraft, Spot


@admin.register(DropZone)
class DropZoneAdmin(admin.ModelAdmin):
    list_display = ('name', 'awos_station_id', 'field_elevation', 'latitude', 'longitude')


@admin.register(Aircraft)
class AircraftAdmin(admin.ModelAdmin):
    list_display = ('name', 'tail_number', 'icao_hex')
    search_fields = ('name', 'tail_number', 'icao_hex')


@admin.register(Spot)
class SpotAdmin(admin.ModelAdmin):
    list_display = ('dt_set', 'active', 'heading', 'lat', 'lon', 'notes')
    list_filter = ('active',)
    ordering = ('-dt_set',)
