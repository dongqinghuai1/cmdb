from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.system.views_feishu import (CallbackView, FeishuAppViewSet,
                                      LoginUrlView)

router = DefaultRouter()
router.register("apps", FeishuAppViewSet, basename="feishu-app")

urlpatterns = [
    path("", include(router.urls)),
    path("login-url/", LoginUrlView.as_view(), name="feishu-login-url"),
    path("callback/", CallbackView.as_view(), name="feishu-callback"),
]
