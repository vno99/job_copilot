# Les modèles sont importés ici pour être enregistrés sur Base.metadata.
from src.infrastructure.db.models.candidate_profile import CandidateProfileModel
from src.infrastructure.db.models.cv_version import CVVersionModel
from src.infrastructure.db.models.job_offer import JobOfferModel
from src.infrastructure.db.models.match_result import MatchResultModel
from src.infrastructure.db.models.search_parameters import SearchParameterModel

__all__ = [
    "CandidateProfileModel",
    "CVVersionModel",
    "JobOfferModel",
    "MatchResultModel",
    "SearchParameterModel",
]
