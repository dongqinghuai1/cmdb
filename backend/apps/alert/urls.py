from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.alert.views import (AlertEventViewSet, AlertRuleViewSet,
                              AlertSilenceViewSet, prometheus_webhook)

router = DefaultRouter()
router.register("rules", AlertRuleViewSet)
router.register("events", AlertEventViewSet)
router.register("silences", AlertSilenceViewSet)

urlpatterns = [path("", include(router.urls)),
               path("webhook/prometheus/", prometheus_webhook)]
