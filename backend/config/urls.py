from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from accounts.views import signup
from analyses import page_views
from analyses.playback import analysis_video
from analyses.dashboard import dashboard
from analyses import camera_preview as camera
from analyses.views import AnalysisJobViewSet

router = SimpleRouter()
router.register("analyses", AnalysisJobViewSet, basename="analysis")

urlpatterns = [
    path("", page_views.analysis_list, name="analysis_list"),
    path("analyses/<int:pk>/", page_views.analysis_detail, name="analysis_detail"),
    path("analyses/<int:pk>/video/<str:kind>/", analysis_video, name="analysis_video"),
    path("accounts/signup/", signup, name="signup"),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("api/", include(router.urls)),
    path("camera/session/", camera.open_camera, name="camera_open"),
    path("camera/session/<uuid:token>/", camera.camera_status, name="camera_status"),
    path("camera/session/<uuid:token>/frame/", camera.camera_frame, name="camera_frame"),
    path("camera/session/<uuid:token>/heartbeat/", camera.camera_heartbeat, name="camera_heartbeat"),
    path("camera/session/<uuid:token>/close/", camera.close_camera, name="camera_close"),
    path("camera/session/<uuid:token>/record/", camera.record_camera, name="camera_record"),
    path("dashboard/", dashboard, name="dashboard"),
    path("admin/", admin.site.urls),
]
