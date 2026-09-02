from django.urls import include, path

from apps.system.views import LoginView, MeView

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("me/", MeView.as_view(), name="me"),
    path("feishu/", include("apps.system.urls_feishu")),
]
