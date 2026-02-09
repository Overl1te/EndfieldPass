from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("language/set", views.set_site_language, name="set_site_language"),
    path("characters/", views.characters_page, name="characters_page"),
    path("privacy/", views.privacy_policy, name="privacy_policy"),
    path("cookies/", views.cookies_policy, name="cookies_policy"),
    path("settings/", views.settings_page, name="settings_page"),
    path("settings/export", views.export_history, name="export_history"),
    path("settings/import", views.import_history, name="import_history"),
    path("settings/cloud/<str:provider>/connect", views.cloud_connect, name="cloud_connect"),
    path("settings/cloud/<str:provider>/callback", views.cloud_callback, name="cloud_callback"),
    path("settings/cloud/<str:provider>/disconnect", views.cloud_disconnect, name="cloud_disconnect"),
    path("settings/cloud/export", views.cloud_export, name="cloud_export"),
    path("settings/cloud/import", views.cloud_import, name="cloud_import"),
    path("import/", views.import_page, name="import_page"),
    path("api/pulls", views.pulls_api, name="pulls_api"),
    path("api/import/session", views.create_session, name="create_session"),
    path("api/import/<int:session_id>/status", views.import_status, name="import_status"),
    path("import/<int:session_id>/", views.import_view, name="import_view"),
    path("api/import/<int:session_id>/pulls", views.pulls_json, name="pulls_json"),
]
