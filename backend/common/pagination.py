"""Pagination with a hard page-size ceiling."""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class CompassPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    # Capped so a client cannot ask for 100_000 rows and turn a list endpoint into a
    # denial-of-service vector against the database.
    max_page_size = 100

    def get_paginated_response(self, data) -> Response:
        return Response(
            {
                "count": self.page.paginator.count,
                "page": self.page.number,
                "page_size": self.get_page_size(self.request),
                "num_pages": self.page.paginator.num_pages,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )
