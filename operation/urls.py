from django.urls import path

from operation import views

app_name = "operation"
urlpatterns = [
    path(
        "line_vehicles_spotting_trend/<int:line_id>/<slug:start_date>/<slug:end_date>/",
        views.LineVehiclesSpottingTrend.as_view(),
        name="line_vehicles_spotting_trend",
    ),
    path(
        "vehicle_spotting_trend/<int:vehicle_id>/<slug:start_date>/<slug:end_date>/",
        views.VehicleSpottingTrend.as_view(),
        name="vehicle_spotting_trend",
    ),
]
