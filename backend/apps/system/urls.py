from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.system import views

router = DefaultRouter()
router.register("users", views.UserViewSet)
router.register("depts", views.OrgDeptViewSet)
router.register("permissions", views.PermissionViewSet)
router.register("roles", views.RoleViewSet)
router.register("credentials", views.CredentialViewSet)
router.register("notify-channels", views.NotifyChannelViewSet)
router.register("audit-logs", views.AuditLogViewSet)
router.register("configs", views.SystemConfigViewSet)
router.register("api-tokens", views.ApiTokenViewSet)

urlpatterns = [path("", include(router.urls))]
