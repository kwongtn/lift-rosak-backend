from django.urls import path

from operation import views

app_name = "operation"
urlpatterns = [
    path(
        "line_vehicles_spotting_trend/<int:line_id>/<slug:start_date>/<slug:end_date>/",
        views.LineVehiclesSpottingTrend.as_view(),
        name="line_vehicles_spotting_trend",
    ),
]
