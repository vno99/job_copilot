"""Agent ``profile_parser`` : parsing d'un CV (Markdown/HTML) uploadé.

Convertit le CV en Markdown, le structure en sections (résumé, compétences,
expérience, formation) et le charge comme ``candidate_profile`` en base.
Chaque upload d'interface crée un nouveau profil (nouvel id).
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from markdownify import markdownify

from config.logger_config import setup_logging
from src.core.domain.candidate_profile import CandidateProfile
from src.core.privacy.anonymize import looks_like_name
from src.infrastructure.db.repositories import candidate_profile_repository
from src.infrastructure.db.session import session_scope

logger = setup_logging(__name__)


# --- Conversion du CV source -------------------------------------------------

def cv_source_to_markdown(source: str | Path) -> str:
    """Lit le CV source et le convertit en Markdown si c'est du HTML."""
    if isinstance(source, Path):
        content = source.read_text(encoding="utf-8")
    else:
        content = source

    head = content.lstrip()[:1000].lower()
    if head.startswith("<html") or head.startswith("<!doctype") or "<body" in head:
        return markdownify(content, heading_style="ATX")
    return content


# --- Découpage en sections ---------------------------------------------------

_SECTION_ALIASES: Dict[str, List[str]] = {
    "resume": ["résumé", "resume", "profil", "summary", "à propos", "a propos"],
    "skills": ["compétences", "competences", "skills", "technologies", "expertise"],
    "experience": ["expérience", "experience", "parcours professionnel"],
    "education": ["formation", "education", "diplômes", "diplomes"],
    # Section « projets » : son contenu n'est pas (encore) exposé par parse_cv,
    # mais il est isolé pour ne pas polluer la section compétences.
    "projects": ["projets", "projet", "projects", "project"],
}

# Ligne de titre en gras seul (``**Résumé**``, ``**Tech Lead — Acme**``), utilisée
# par les CV exportés depuis des éditeurs qui ne produisent pas de headings ``#``.
_BOLD_ONLY_RE = re.compile(r"^\*\*(.+?)\*\*\s*$")

# Période en gras rattachée au titre du poste en cours
# (``**01/2022 — 06/2025**``, ``**07/2021 - 01/2022**``, ``**Janvier 2022**``,
# ``**depuis 03/2024**``…). Sans détection, deux postes consécutifs sans puces
# (``**Poste 1**`` puis ``**Poste 2**``) seraient fusionnés en « Poste 1 — Poste 2 » :
# seules les lignes qui commencent par une date sont traitées comme une période.
_PERIOD_RE = re.compile(
    r"^(?:"
    r"\d{1,2}/\d{2,4}"                       # 01/2022
    r"|\d{1,2}-\d{2,4}"                      # 07-2021
    r"|\d{4}"                                # 2022
    r"|[a-zàâçéèêëîïôûùüÿ]{3,}\s+\d{2,4}"    # janvier 2022
    r"|(?:depuis|à ce jour|aujourd'hui|présent)"
    r")"
    r"(?:\s*(?:—|-|–|/|au|à)\s*.+)?$",
    re.IGNORECASE,
)


def _normalize_markdown(markdown: str) -> str:
    """Convertit les titres de section en gras (``**Résumé**``) en headings ``#``.

    Les CV exportés mettent souvent les titres en gras plutôt qu'en headings
    Markdown. On rend uniquement les titres reconnus compatibles avec
    ``_split_sections``, sans toucher au reste du contenu (headline, postes…).
    """
    out: List[str] = []
    for line in markdown.splitlines():
        match = _BOLD_ONLY_RE.match(line.strip())
        if match and _is_section_title(match.group(1)):
            out.append(f"# {match.group(1).strip()}")
        else:
            out.append(line)
    return "\n".join(out)


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-zà-ÿ0-9\s]", "", title.strip().lower())


def _is_section_title(title: str) -> bool:
    norm = _normalize_title(title)
    return any(alias in norm for aliases in _SECTION_ALIASES.values() for alias in aliases)


def _split_sections(markdown: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            norm = _normalize_title(title)
            matched = next(
                (key for key, aliases in _SECTION_ALIASES.items()
                 if any(alias in norm for alias in aliases)),
                None,
            )
            if matched is not None:
                current = matched
                sections.setdefault(current, [])
            elif current is not None:
                # Sous-heading à l'intérieur d'une section (ex. ### Poste)
                sections[current].append(stripped)
            else:
                current = None
            continue
        if current:
            sections[current].append(stripped)

    return sections


def _extract_headline(markdown: str) -> str:
    plain_candidate = ""
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title and not _is_section_title(title):
                return title
        else:
            match = _BOLD_ONLY_RE.match(stripped)
            if match and not _is_section_title(match.group(1)):
                # Titre en gras (ex. ``**NOUANE Victor**``).
                return match.group(1).strip()
            # Nom en première ligne simple (ni ``#`` ni ``**``), ex. ``Jean
            # Dupont`` — même détection que l'anonymisation (``looks_like_name``),
            # pour que le headline (utilisé comme nom lors du matching) ne soit
            # jamais vide quand le CV ne structure pas son nom en titre.
            if not plain_candidate and looks_like_name(stripped):
                plain_candidate = stripped
    return plain_candidate


# --- Extraction du contenu ---------------------------------------------------

def _extract_skills(lines: List[str]) -> List[str]:
    skills: List[str] = []
    for line in lines:
        if not line:
            continue
        item = re.sub(r"^[-*•]\s*", "", line).strip()
        # Préfixe de catégorie en gras (ex. ``**Data Engineering** : Python, ...``).
        item = re.sub(r"^\*\*(.+?)\*\*\s*:\s*", "", item)
        item = item.replace("**", "").strip()
        if not item:
            continue
        if "," in item:
            skills.extend(s.strip() for s in item.split(",") if s.strip())
        else:
            skills.append(item)
    return skills


def _parse_experience_blocks(lines: List[str]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            current = {"title": stripped.lstrip("#").strip(), "bullets": []}
            blocks.append(current)
            continue
        bold = _BOLD_ONLY_RE.match(stripped)
        if bold:
            text = bold.group(1).strip()
            if current is None or current["bullets"]:
                # Nouveau poste (ex. ``**Tech Lead Java — Acme**``)…
                current = {"title": text, "bullets": []}
                blocks.append(current)
            elif _PERIOD_RE.match(text):
                # …ou date/période rattachée au titre en cours (``**01/2022 — 06/2025**``).
                current["title"] = f"{current['title']} — {text}"
            else:
                # Deux postes consécutifs sans puces entre les deux
                # (``**Poste 1**`` puis ``**Poste 2**``) : pas une période — nouveau
                # poste, sinon les titres fusionneraient (« Poste 1 — Poste 2 »).
                current = {"title": text, "bullets": []}
                blocks.append(current)
            continue
        if current is None:
            current = {"title": stripped, "bullets": []}
            blocks.append(current)
            continue
        if re.match(r"^[-*•]\s", stripped):
            current["bullets"].append(re.sub(r"^[-*•]\s*", "", stripped).strip())
        elif not current["bullets"]:
            # ligne descriptive (entreprise / période) avant la première puce
            current["title"] = f"{current['title']} — {stripped}"
        else:
            # Ligne de contenu après les puces (ex. ``**Stack** : Java 17, ...``) :
            # conservée comme puce pour ne pas perdre d'information technique.
            current["bullets"].append(stripped.replace("**", ""))

    return blocks


def parse_cv(markdown: str) -> Dict[str, Any]:
    """Structure un CV Markdown en dict de profil (fonction pure)."""
    markdown = _normalize_markdown(markdown)
    sections = _split_sections(markdown)
    headline = _extract_headline(markdown)

    return {
        "headline": headline,
        "summary": " ".join(sections.get("resume", [])).strip() or None,
        "skills": _extract_skills(sections.get("skills", [])),
        "experiences": _parse_experience_blocks(sections.get("experience", [])),
        "education": _extract_skills(sections.get("education", [])),
    }


# --- Service -----------------------------------------------------------------

class ProfileParserService:
    """Crée des profils candidats depuis un CV uploadé (interface)."""

    @staticmethod
    def _generate_profile_name(session: Any, filename: Optional[str]) -> str:
        """Nom de profil unique, dérivé du nom de fichier ou générique."""
        base = Path(filename or "upload").stem or "upload"
        if candidate_profile_repository.get_by_name(session, base) is None:
            return base
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{base}_{suffix}"
        counter = 1
        while candidate_profile_repository.get_by_name(session, name) is not None:
            name = f"{base}_{suffix}_{counter}"
            counter += 1
        return name

    def run_from_content(
        self,
        content: str,
        profile_name: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> int:
        """Crée un nouveau profil depuis un CV fourni en texte (upload d'interface).

        Un **nouvel id** est créé à chaque appel (jamais d'upsert). Le profil
        devient actif uniquement si aucun profil actif n'existe déjà. Le contenu
        brut est conservé dans ``cv_raw_json.raw_content``.

        Args:
            content: contenu du CV (Markdown ou HTML).
            profile_name: nom du profil ; généré unique si absent.
            filename: nom du fichier d'origine, conservé comme ``source_path``.

        Returns:
            L'id du nouveau ``candidate_profile``.
        """
        markdown = cv_source_to_markdown(content)
        parsed = parse_cv(markdown)

        with session_scope() as session:
            is_active = candidate_profile_repository.get_active(session) is None
            name = profile_name or self._generate_profile_name(session, filename)

            profile = CandidateProfile(
                profile_name=name,
                headline=parsed["headline"],
                summary=parsed["summary"],
                skills=parsed["skills"],
                experiences=parsed["experiences"],
                education=parsed["education"],
                source_path=filename or "",
            )

            record = profile.to_persist_dict()
            record["cv_raw_json"]["raw_content"] = content
            record["is_active"] = is_active
            profile_id = candidate_profile_repository.insert(session, record)

        logger.info(
            "Profil uploadé '%s' (id=%s, actif=%s)", name, profile_id, is_active
        )
        return profile_id
