from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.ncm import views

router = DefaultRouter()
router.register("backups", views.ConfigBackupViewSet, basename="ncm-backup")
router.register("change-events", views.ConfigChangeEventViewSet)
router.register("baseline-rules", views.BaselineRuleViewSet)
router.register("baseline-results", views.BaselineResultViewSet)

urlpatterns = [path("", include(router.urls))]
