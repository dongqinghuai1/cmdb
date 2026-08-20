from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.monitor import views

router = DefaultRouter()
router.register("collectors", views.CollectorNodeViewSet)
router.register("logs", views.LogRecordViewSet, basename="log")

urlpatterns = [path("", include(router.urls))]
