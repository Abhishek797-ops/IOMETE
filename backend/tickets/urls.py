from rest_framework.routers import DefaultRouter

from .views import TicketViewSet

router = DefaultRouter()
router.register("", TicketViewSet, basename="ticket")

urlpatterns = router.urls
