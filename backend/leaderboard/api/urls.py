"""URL map for the versioned leaderboard API.

The version lives in the *path* (`/api/v1/leaderboard/`) rather than in a
header or a query parameter, so a breaking change can ship as `/api/v2/`
alongside a still-working v1 while the frontend migrates. These are all
read-only GETs, so there is no compatibility surface beyond the response shape.

`category` and `key` are intentionally permissive path segments: they are
validated inside the view, so that an unknown category returns a 404 body
*listing the valid values* rather than a bare URL-resolution failure.
"""

from django.urls import path

from . import discussion_views, views

app_name = "leaderboard"

urlpatterns = [
    path("overview/", views.OverviewView.as_view(), name="overview"),
    path("categories/", views.CategoryIndexView.as_view(), name="category-index"),
    path(
        "categories/<str:category>/",
        views.CategoryView.as_view(),
        name="category-detail",
    ),
    path(
        "artificial-analysis/",
        views.ArtificialAnalysisView.as_view(),
        name="artificial-analysis",
    ),
    path("models/<str:key>/", views.ModelDetailView.as_view(), name="model-detail"),
    path("metadata/", views.MetadataView.as_view(), name="metadata"),
    path("unmatched/", views.UnmatchedView.as_view(), name="unmatched"),
    # Discussions. A separate module rather than three more classes in `views.py`
    # so the forbidden-import grep in `test_api_no_network.py` covers them
    # explicitly, and `entities/` is declared before the `{hn_id}` route so the
    # literal is not swallowed by the converter.
    path(
        "discussions/",
        discussion_views.DiscussionListView.as_view(),
        name="discussion-list",
    ),
    path(
        "discussions/entities/",
        discussion_views.DiscussionEntityIndexView.as_view(),
        name="discussion-entities",
    ),
    path(
        "discussions/<str:hn_id>/",
        discussion_views.DiscussionDetailView.as_view(),
        name="discussion-detail",
    ),
]
