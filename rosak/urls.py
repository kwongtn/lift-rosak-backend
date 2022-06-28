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
from django.urls import include, path
from django.views.decorators.csrf import csrf_exempt
from graphene_django.views import GraphQLView

from .schema import schema

urlpatterns = (
    [
        path("health-check/", include("health_check.urls")),
        path(settings.ADMIN_PATH, admin.site.urls),
        path(
            "graphql/",
            csrf_exempt(
                GraphQLView.as_view(
                    graphiql=True,
                    schema=schema,
                )
            ),
        ),
        path("oauth2/v1/", include("oauth2.urls", namespace="oauth2_v1")),
    ]
    # These are served in debug mode only
    + static("media/", document_root=settings.MEDIA_ROOT)
    + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
)

# if settings.USE_SILK:
#     urlpatterns += [path("silk/", include("silk.urls", namespace="silk"))]

# if settings.DEBUG:
#     import debug_toolbar

#     urlpatterns += [
#         path("__debug__/", include(debug_toolbar.urls)),
#     ]
