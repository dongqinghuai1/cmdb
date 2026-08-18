from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.inspect.views import (InspectRunViewSet, InspectTaskViewSet,
                                InspectTemplateViewSet)

router = DefaultRouter()
router.register("templates", InspectTemplateViewSet)
router.register("tasks", InspectTaskViewSet)
router.register("runs", InspectRunViewSet)

urlpatterns = [path("", include(router.urls))]
