from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.cmdb import views

router = DefaultRouter()
router.register("models", views.CiModelViewSet)
router.register("devices", views.DeviceViewSet)
router.register("groups", views.DeviceGroupViewSet)
router.register("businesses", views.BusinessViewSet)

urlpatterns = [path("", include(router.urls))]

