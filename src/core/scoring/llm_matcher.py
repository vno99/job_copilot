"""Scoring offre / profil par LLM (mistral-small-latest).

Remplace l'ancien moteur heuristique : le LLM évalue directement la compatibilité
d'un profil avec une annonce et produit un score global, une décomposition par
critère, les points forts, les écarts et des explications personnalisées pour
ajuster la candidature.

Le matching **exige** le LLM : sans clé API ou en cas de réponse invalide,
``compute_llm_match`` lève ``LLMMatchingError`` (pas de fallback heuristique).
Réutilise l'instance ``score_engine.LLM`` (``ChatMistralAI``), lue au moment de
l'appel pour que le mock du conftest continue de fonctionner.
"""

import json
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage

from config.logger_config import setup_logging
from src.core.scoring import score_engine

logger = setup_logging(__name__)

# Marqueurs de délimitation du prompt (réutilisés par le mock du conftest).
JOB_MARKER = "=== OFFRE D'EMPLOI ==="
PROFILE_MARKER = "=== PROFIL CANDIDAT ==="
OUTPUT_MARKER = "JSON ATTENDU"

# Décomposition du score produite par le LLM, telle qu'attendue par le front
# (web/src/components/ui.tsx) et stockée dans ``match_result.score_breakdown``.
BREAKDOWN_KEYS = (
    "title_score",
    "skills_score",
    "experience_score",
    "education_score",
)

# Borne la description envoyée au LLM (coût / latence), sans tronquer les offres
# réalistes.
MAX_DESCRIPTION_CHARS = 6000

# Borne identique pour le texte brut du CV (anonymisé) envoyé au LLM.
MAX_CV_CHARS = 8000


class LLMMatchingError(RuntimeError):
    """Le LLM est indisponible (clé absente, erreur API, réponse invalide)."""


SYSTEM_PROMPT = """
Tu es un recruteur technique senior.
Compare une offre d'emploi et un profil candidat, puis évalue leur compatibilité.
Réponds UNIQUEMENT en JSON valide, sans texte autour.
"""

USER_PROMPT_TEMPLATE = """
Compare l'offre d'emploi et le profil candidat ci-dessous et évalue la compatibilité.

{JOB_MARKER}
{job}

{PROFILE_MARKER}
{profile}

Le profil ci-dessus est un CV anonymisé : nom, téléphone, email, adresse et liens
ont été remplacés par des placeholders ([NOM], [EMAIL]…). Juge uniquement les
compétences, l'expérience et la formation, pas les données personnelles.

Produis UNIQUEMENT un JSON valide, sans texte autour, avec :
- "score" : note globale de compatibilité entre 0 et 100 (entier ou décimal).
  Ce n'est PAS une moyenne pondérée : juge ce qui est important pour ce poste
  (expérience, compétences, soft skills, adéquation du parcours...).
- "score_breakdown" : objet avec ces 4 clés numériques entre 0 et 1 :
    - "title_score" : adéquation de l'intitulé / du périmètre du poste,
    - "skills_score" : couverture des compétences requises,
    - "experience_score" : pertinence de l'expérience,
    - "education_score" : adéquation de la formation.
- "strengths" : tableau de 2 à 5 points forts concrets du profil pour ce poste.
- "weaknesses" : tableau de 2 à 5 écarts / points faibles par rapport à l'annonce.
- "missing_skills" : tableau des noms des compétences demandées par l'offre et
  absentes du profil (noms courts, en minuscules). Ne PAS inventer : uniquement
  ce que l'offre demande explicitement.
- "explanation" : 3 à 6 phrases en français, personnalisées, pour ajuster la
  candidature : quoi mettre en avant dans le CV et la lettre de motivation,
  comment compenser les écarts.

RÈGLES :
1. "score" et chaque valeur de "score_breakdown" doivent être des NOMBRES.
2. Les tableaux et "explanation" doivent exister (tableaux éventuellement vides).
3. Ne pas inventer de compétences dans "missing_skills".

{OUTPUT_MARKER} (exemple) :
{{
  "score": 72,
  "score_breakdown": {{"title_score": 0.9, "skills_score": 0.6, "experience_score": 0.8, "education_score": 0.5}},
  "strengths": ["Maîtrise de Python et SQL"],
  "weaknesses": ["Pas d'expérience Databricks"],
  "missing_skills": ["databricks"],
  "explanation": "Mettez en avant vos pipelines Airflow et votre expérience en traitement de données volumineuses..."
}}
"""


def _build_prompt(job: Dict[str, Any], profile: Dict[str, Any]) -> str:
    """Construit le prompt utilisateur avec l'offre et le profil sérialisés.

    Le profil est le CV brut anonymisé (``raw_cv``) ; sa longueur est bornée.
    """
    description = job.get("description") or ""
    job_payload = dict(job)
    if len(description) > MAX_DESCRIPTION_CHARS:
        job_payload["description"] = description[:MAX_DESCRIPTION_CHARS] + "…"

    raw_cv = profile.get("raw_cv") or ""
    profile_payload = dict(profile)
    if len(raw_cv) > MAX_CV_CHARS:
        profile_payload["raw_cv"] = raw_cv[:MAX_CV_CHARS] + "…"

    logger.debug(f"profile_payload envoye au LLM pour le matching : {profile_payload}")

    return USER_PROMPT_TEMPLATE.format(
        JOB_MARKER=JOB_MARKER,
        PROFILE_MARKER=PROFILE_MARKER,
        OUTPUT_MARKER=OUTPUT_MARKER,
        job=json.dumps(job_payload, ensure_ascii=False, default=str),
        profile=json.dumps(profile_payload, ensure_ascii=False, default=str),
    )


def _strip_code_fences(text: str) -> str:
    """Enlève les backticks éventuels autour du contenu renvoyé par le LLM.

    Retire la ligne de fence de tête (éventuellement suivie du langage : json,
    markdown, md…) et la fence de fin. Gère les fences nues (`````) comme les
    fences typées — utilisé par le matching (JSON) et la génération de CV
    (Markdown).
    """
    text = (text or "").strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline == -1:
            text = text[3:]
        else:
            text = text[first_newline + 1 :]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _as_float(value: Any) -> float:
    """Coerce une valeur en float ; ValueError si impossible."""
    return float(value)


def _as_str_list(items: Any) -> list:
    if not items:
        return []
    return [str(item) for item in items if str(item).strip()]


def _normalize_result(data: Dict[str, Any]) -> Dict[str, Any]:
    """Valide / normalise la réponse LLM en structure persistable.

    Un score manquant ou non-numérique rend la réponse invalide : le matching
    échoue (``LLMMatchingError``) plutôt que de persistre un score arbitraire.
    """
    try:
        score = _as_float(data.get("score"))
    except (TypeError, ValueError):
        raise LLMMatchingError("Réponse LLM invalide : champ 'score' absent ou non-numérique")

    # Garde d'échelle : le LLM peut répondre sur une échelle 0-1 (comme les
    # valeurs de ``score_breakdown`` du même prompt) plutôt que 0-100. Un score
    # dans [0, 1] est converti en pourcentage (0.85 → 85).
    if 0 <= score <= 1:
        score = score * 100

    breakdown = data.get("score_breakdown") or {}
    if not isinstance(breakdown, dict):
        breakdown = {}

    normalized_breakdown: Dict[str, float] = {}
    for key in BREAKDOWN_KEYS:
        try:
            normalized_breakdown[key] = round(
                max(0.0, min(1.0, _as_float(breakdown.get(key, 0.0)))), 3
            )
        except (TypeError, ValueError):
            normalized_breakdown[key] = 0.0

    return {
        "score": round(max(0.0, min(100.0, score)), 2),
        "score_breakdown": normalized_breakdown,
        "strengths": _as_str_list(data.get("strengths")),
        "weaknesses": _as_str_list(data.get("weaknesses")),
        "missing_skills": _as_str_list(data.get("missing_skills")),
        "explanation": str(data.get("explanation") or "").strip(),
    }


def compute_llm_match(job: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Calcule et normalise le score de compatibilité LLM offre × profil.

    Args:
        job: dict de l'offre (title, company, location, contract_type,
            experience, diploma, description, skills_extracted).
        profile: dict du profil — ``raw_cv`` : texte brut du CV anonymisé.

    Returns:
        Dict avec ``score`` (0-100), ``score_breakdown`` (4 clés 0-1),
        ``strengths``, ``weaknesses``, ``missing_skills``, ``explanation`` —
        mappé tel quel sur ``match_result``.

    Raises:
        LLMMatchingError: si la clé API est absente, l'appel échoue ou la
            réponse n'est pas un JSON exploitable.
    """
    if score_engine.LLM is None:
        logger.error("MISTRAL_API_KEY absente : matching LLM indisponible.")
        raise LLMMatchingError("MISTRAL_API_KEY absente : matching LLM indisponible.")

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=_build_prompt(job, profile)),
    ]

    try:
        response = score_engine.LLM.invoke(messages)
        response_text = _strip_code_fences(response.content)
        result = json.loads(response_text)
        if not isinstance(result, dict):
            raise LLMMatchingError("Réponse LLM invalide : JSON non-objet")
        return _normalize_result(result)
    except LLMMatchingError:
        raise
    except json.JSONDecodeError as exc:
        logger.error("Matching LLM : erreur de parsing JSON : %s", exc)
        raise LLMMatchingError("Matching LLM : réponse JSON invalide") from exc
    except Exception as exc:
        logger.error("Matching LLM : erreur API : %s", exc)
        raise LLMMatchingError(f"Matching LLM : erreur API ({type(exc).__name__})") from exc
