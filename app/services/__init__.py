"""Application services shared by bot, dispatcher, API, and workers."""

from app.services.admission import AdmissionService
from app.services.quota import QuotaService

__all__ = ["AdmissionService", "QuotaService"]
