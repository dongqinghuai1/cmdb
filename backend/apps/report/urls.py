from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.report import views

router = DefaultRouter()
router.register("snapshots", views.ReportSnapshotViewSet)
router.register("schedules", views.ReportScheduleViewSet)

urlpatterns = [path("", include(router.urls))]
