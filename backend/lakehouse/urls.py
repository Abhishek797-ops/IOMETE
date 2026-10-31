from django.urls import path

from .views import (
    CatalogTableView,
    DatasetView,
    PlaygroundStatusView,
    RunQueryView,
    SampleQueriesView,
)

urlpatterns = [
    path("status/", PlaygroundStatusView.as_view(), name="lakehouse-status"),
    path("dataset/", DatasetView.as_view(), name="lakehouse-dataset"),
    path("sample-queries/", SampleQueriesView.as_view(), name="lakehouse-samples"),
    path("query/", RunQueryView.as_view(), name="lakehouse-query"),
    path("catalog/<str:namespace>/<str:table>/", CatalogTableView.as_view(),
         name="lakehouse-catalog-table"),
]
