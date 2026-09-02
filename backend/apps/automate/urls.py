from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.automate import views

router = DefaultRouter()
router.register("scripts", views.ScriptViewSet)
router.register("script-runs", views.ScriptRunViewSet, basename="script-run")
router.register("approvals", views.ApprovalViewSet, basename="approval")
router.register("firmware-packages", views.FirmwarePackageViewSet)
router.register("firmware-upgrades", views.FirmwareUpgradePlanViewSet)

urlpatterns = [path("", include(router.urls))]
