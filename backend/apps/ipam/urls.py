from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.ipam import views

router = DefaultRouter()
router.register("vlans", views.VlanViewSet)
router.register("subnets", views.SubnetViewSet)
router.register("ips", views.IpViewSet)

urlpatterns = [path("", include(router.urls))]
