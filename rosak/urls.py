"""rosak URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.decorators.csrf import csrf_exempt

from rosak.context import CustomGraphQLView

from . import custom_view
from .schema import schema

urlpatterns = (
    [
        path("health-check/", include("health_check.urls")),
        path("admin/", admin.site.urls),
        path("hijack/", include("hijack.urls")),
        re_path("^advanced_filters/", include("advanced_filters.urls")),
        path(
            "graphql/",
            CustomGraphQLView.as_view(
                graphiql=True if settings.DEBUG else False,
                schema=schema,
            ),
        ),
        path("sentry/", csrf_exempt(custom_view.sentry)),
        path("version/", csrf_exempt(custom_view.git_version)),
        # path("oauth2/v1/", include("oauth2.urls", namespace="oauth2_v1")),
    ]
    # These are served in debug mode only
    + static("media/", document_root=settings.MEDIA_ROOT)
    + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
)

# if settings.USE_SILK:
#     urlpatterns += [path("silk/", include("silk.urls", namespace="silk"))]

if settings.DEBUG:
    import debug_toolbar

    def trigger_error(request):
        division_by_zero = 1 / 0  # noqa

    urlpatterns += [
        path("__debug__/", include(debug_toolbar.urls)),
        path("sentry-debug/", trigger_error),
    ]

urlpatterns += [
    re_path("/?", csrf_exempt(custom_view.redirect_view)),
]
