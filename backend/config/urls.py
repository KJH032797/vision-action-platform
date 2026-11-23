from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from accounts.views import signup
from analyses import page_views
from analyses.views import AnalysisJobViewSet

router = SimpleRouter()
router.register("analyses", AnalysisJobViewSet, basename="analysis")

urlpatterns = [
    path("", page_views.analysis_list, name="analysis_list"),
    path("analyses/<int:pk>/", page_views.analysis_detail, name="analysis_detail"),
    path("accounts/signup/", signup, name="signup"),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("api/", include(router.urls)),
    path("admin/", admin.site.urls),
]