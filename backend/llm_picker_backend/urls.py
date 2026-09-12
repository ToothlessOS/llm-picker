"""Root URL configuration.

Everything the frontend consumes is namespaced under
`/api/v1/leaderboard/`; the Django admin stays at `/admin/` for the
alias-review workflow that the unmatched report feeds into.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/leaderboard/", include("leaderboard.api.urls")),
]
