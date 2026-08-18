from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.alert.views import AlertEventViewSet, AlertRuleViewSet

router = DefaultRouter()
router.register("rules", AlertRuleViewSet)
router.register("events", AlertEventViewSet)

urlpatterns = [path("", include(router.urls))]
