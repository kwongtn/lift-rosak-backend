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
        "line_vehicles_status_trend_count/<int:line_id>/<slug:source_str>/<slug:start_date>/<slug:end_date>/",
        views.LineVehiclesStatusTrendCount.as_view(),
        name="line_vehicles_status_trend_count",
    ),
    path(
        "vehicle_spotting_trend/<int:vehicle_id>/<slug:start_date>/<slug:end_date>/",
        views.VehicleSpottingTrend.as_view(),
        name="vehicle_spotting_trend",
    ),
]
