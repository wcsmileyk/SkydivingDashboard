from django.db import models

# Create your models here.

class DropZone(models.Model):
    name = models.CharField(max_length=200)
    latitude = models.FloatField()
    longitude = models.FloatField()
    field_elevation = models.FloatField()
    awos_station_id = models.CharField(max_length=5)
    adsb_url = models.URLField()
    no_wind_heading = models.IntegerField()


class Aircraft(models.Model):
    name = models.CharField(max_length=200)
    icao_hex = models.CharField(max_length=200)
    tail_number = models.CharField(max_length=200)


class Spot(models.Model):
    dt_set = models.DateTimeField()
    lat = models.FloatField()
    lon = models.FloatField()
    heading = models.IntegerField()
    active = models.BooleanField(default=False)
    exit_altitude = models.IntegerField(default=12500)
    notes = models.TextField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.active:
            Spot.objects.exclude(pk=self.pk).update(active=False)
        super().save(*args, **kwargs)