from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('api/weather/', views.api_weather, name='api_weather'),
    path('api/aircraft/', views.api_aircraft, name='api_aircraft'),
    path('api/spot/', views.api_spot, name='api_spot'),
    path('api/winds/', views.api_winds, name='api_winds'),
]
