"""根路由：API 统一前缀 /api/v1/（PRD 5.16 开放平台）。"""
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

api_v1 = [
    path("auth/", include("apps.system.urls_auth")),
    path("system/", include("apps.system.urls")),
    path("dcim/", include("apps.dcim.urls")),
    path("cmdb/", include("apps.cmdb.urls")),
    path("monitor/", include("apps.monitor.urls")),
    path("usage/", include("apps.usage.urls")),
    path("alerts/", include("apps.alert.urls")),
    path("inspects/", include("apps.inspect.urls")),
    path("ipam/", include("apps.ipam.urls")),
    path("topo/", include("apps.topo.urls")),
    path("ncm/", include("apps.ncm.urls")),
    path("automate/", include("apps.automate.urls")),
    path("changes/", include("apps.change.urls")),
    path("ai/", include("apps.ai.urls")),
    path("reports/", include("apps.report.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
