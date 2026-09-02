from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.change import views

router = DefaultRouter()
router.register("incidents", views.IncidentTicketViewSet, basename="incident")
router.register("change-tickets", views.ChangeTicketViewSet, basename="change-ticket")

urlpatterns = [path("", include(router.urls))]
