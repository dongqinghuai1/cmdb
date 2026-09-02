from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.dcim import views

router = DefaultRouter()
router.register("regions", views.RegionViewSet)
router.register("sites", views.SiteViewSet)
router.register("racks", views.RackViewSet)
router.register("reservations", views.RackReservationViewSet)
router.register("cables", views.CableViewSet)
router.register("site-objects", views.SiteObjectViewSet)
router.register("op-tickets", views.DcimTicketViewSet)

urlpatterns = [path("", include(router.urls))]
