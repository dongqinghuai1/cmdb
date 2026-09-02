from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.topo import views

router = DefaultRouter()
router.register("lldp-neighbors", views.LldpNeighborViewSet)
router.register("topologies", views.TopologyViewSet)
router.register("edges", views.TopologyEdgeViewSet)

urlpatterns = [
    path("graph/", views.GraphView.as_view(), name="topo-graph"),
    path("lldp-discover/", views.LldpDiscoverView.as_view(), name="topo-lldp-discover"),
    path("", include(router.urls)),
]
