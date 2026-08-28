from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class CandidateProfile:
    """Profil candidat structuré, parsé depuis un CV source.

    Les métadonnées non-colonne (``source_path``) sont portées par ``cv_raw_json``
    en base, avec le contenu brut ``raw_content``.
    """

    profile_name: str
    headline: str = ""
    summary: str = ""
    skills: List[str] = field(default_factory=list)
    experiences: List[Dict[str, Any]] = field(default_factory=list)
    education: List[str] = field(default_factory=list)
    source_path: str = ""

    def to_persist_dict(self) -> Dict[str, Any]:
        """Dictionnaire mappé sur la table ``candidate_profile``."""
        return {
            "profile_name": self.profile_name,
            "headline": self.headline or None,
            "summary": self.summary or None,
            "cv_raw_json": {
                "source_path": self.source_path,
            },
            "skills": self.skills,
            "experiences": self.experiences,
            "education": self.education,
        }

    @classmethod
    def from_row(cls, row: Any) -> "CandidateProfile":
        """Reconstruit un profil à partir d'une ligne ``CandidateProfileModel``."""
        meta = row.cv_raw_json or {}
        return cls(
            profile_name=row.profile_name,
            headline=row.headline or "",
            summary=row.summary or "",
            skills=row.skills or [],
            experiences=row.experiences or [],
            education=row.education or [],
            source_path=meta.get("source_path", "") or "",
        )
