"""Génération de lettre de motivation par LLM.

Le LLM rédige une lettre de motivation pour une offre, à partir du CV du
candidat (généré ou brut), **anonymisé** : nom, téléphone, email, code postal +
ville et LinkedIn ne sont jamais transmis. Aucune coordonnée n'est réinjectée
côté serveur : la lettre est **anonyme** et se termine par la formule de
politesse du LLM (un nettoyage retire les placeholders résiduels via
``privacy.anonymize.clean_letter_markdown``).

La génération se fait en **deux passes** (``humanize_letter_markdown``) :
1. La pass 1 (``generate_letter_markdown``) rédige la lettre — comportement
   historique, inchangé, sur ``GENERATION_LLM`` (``mistral-small-latest``).
2. La pass 2 est **best-effort** : le LLM réécrit systématiquement la lettre de
   la pass 1 avec un style humain (``_rewrite_letter_human``). En cas d'échec de
   la pass 2, la lettre de la pass 1 est conservée. La réécriture passe par
   l'instance dédiée ``HUMANIZE_LLM`` (**``mistral-large-latest``**, partagée
   avec la pass 2 du CV), indépendante du modèle de génération.

La pass 1 **exige** le LLM : sans clé ou en cas de réponse vide/invalide,
``generate_letter_markdown`` lève ``LetterGenerationError`` (→ HTTP 502), pas de
fallback.
"""

import json
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage

from config.logger_config import setup_logging
from src.core.scoring import score_engine
from src.core.scoring.llm_matcher import JOB_MARKER, PROFILE_MARKER, _strip_code_fences

logger = setup_logging(__name__)

# Marqueur dédié au prompt de lettre, utilisé par le mock du conftest pour
# distinguer la lettre du matching et de la génération de CV (le prompt lettre
# contient aussi PROFIL_MARKER).
LETTER_MARKER = "=== LETTRE DE MOTIVATION ==="

# Marqueurs de la pass 2 (réécriture « humaine »). Le prompt de réécriture ne
# contient PAS LETTER_MARKER (le mock du conftest branchirait sur la pass 1) :
# la 1re lettre y est délimitée par FIRST_LETTER_MARKER.
REWRITE_MARKER = "=== RÉÉCRITURE HUMAINE ==="
FIRST_LETTER_MARKER = "=== LETTRE INITIALE ==="


class LetterGenerationError(RuntimeError):
    """Le LLM est indisponible (clé absente, erreur API, réponse vide/invalide)."""


SYSTEM_PROMPT = """
Tu es un expert en rédaction de lettres de motivation pour le marché francophone.
Tu rédiges une lettre de motivation pour une offre d'emploi, à partir du CV du
candidat, sans rien inventer.
Réponds UNIQUEMENT en Markdown, sans texte autour.
"""

USER_PROMPT_TEMPLATE = """
Rédige une lettre de motivation en français pour l'offre d'emploi ci-dessous, à
partir du CV du candidat fourni.

{JOB_MARKER}
{job}

{PROFILE_MARKER}
{profile}

Le CV ci-dessus est anonymisé : nom, téléphone, email, code postal + ville et
LinkedIn sont remplacés par des placeholders ([NOM], [EMAIL]…). La lettre
finale ne contient **aucune coordonnée** : ne les écris pas toi-même.

{LETTER_MARKER}

RÈGLES STRICTES :
1. Structure : accroche sur le poste visé et l'entreprise (qui montre que j'ai
   vraiment lu l'offre), puis trois paragraphes — pourquoi je postule (lien
   personnel avec l'entreprise ou l'offre), ce que je peux apporter (expérience,
   compétences, résultats concrets), une touche personnelle (ce qui me
   différencie) — et une conclusion courte.
2. Ne PAS inventer de compétences, d'expériences, de formations, de chiffres ou
   de réalisations absents du CV fourni. La touche personnelle doit être tirée
   des faits réels du CV (projets, expériences, diplômes) ; si rien ne s'y
   prête, écris une motivation factuelle pour le poste — sans rien inventer.
3. Ne PAS écrire d'en-tête de coordonnées (nom, email, téléphone, adresse,
   LinkedIn) en haut de la lettre.
4. Termine par une formule de politesse (ex. « Cordialement, ») suivie d'aucune
   signature : pas de nom, pas de coordonnées, pas de placeholders en fin de
   lettre. La phrase de conclusion juste avant peut être non conventionnelle
   (pas de « je me tiens à votre disposition »), mais la formule de politesse
   reste présente.
5. Style et tonalité : lettre courte (environ 200 mots), phrases de longueur
   variable, ton personnel et naturel — comme si je parlais à un recruteur
   autour d'un café. Évite les phrases trop formelles ou pompeuses.
   Privilégie l'authenticité.
6. À bannir absolument : les phrases toutes faites (« Je suis un professionnel
   motivé », « Permettez-moi de vous exprimer », « Dans l'attente de votre
   retour »), les listes à puces, les adjectifs vagues (dynamique, rigoureux,
   polyvalent) sans exemple concret, et une structure trop symétrique (chaque
   paragraphe exactement de la même longueur).
7. Objectif : une lettre qui semble écrite par un humain, avec son style, ses
   petites imperfections et ses envies réelles.
8. Réponds UNIQUEMENT en Markdown, sans blocs de code ni texte autour.
"""

# --- Pass 2 : réécriture « humaine » -------------------------------------------

REWRITE_SYSTEM_PROMPT = """
Tu es un expert en rédaction de lettres de motivation qui sonnent humain, pour le
marché francophone.
On te remet une lettre visiblement rédigée par un LLM : tu la réécris de bout en
bout pour qu'elle semble écrite par un humain, en t'appuyant sur les faits du CV
(sans rien inventer).
Réponds UNIQUEMENT en Markdown, sans texte autour.
"""

REWRITE_USER_PROMPT_TEMPLATE = """
Réécris la lettre de motivation ci-dessous, visiblement rédigée par un LLM, pour
qu'elle sonne comme écrite par un humain.

{FIRST_LETTER_MARKER}
{first_letter}

{JOB_MARKER}
{job}

{PROFILE_MARKER}
{profile}

Le CV ci-dessus est anonymisé : nom, téléphone, email, code postal + ville et
LinkedIn sont remplacés par des placeholders ([NOM], [EMAIL]…). La lettre
finale ne contient **aucune coordonnée** : ne les écris pas toi-même.

{REWRITE_MARKER}

RÈGLES STRICTES (réécrire la lettre fournie, ne pas en rédiger une nouvelle
générique) :
1. Varie la structure : paragraphes de longueur variable, phrases courtes
   percutantes, questions directes. Supprime le schéma scolaire
   « accroche → développement → conclusion » et la symétrie trop parfaite
   (paragraphes de longueur quasi-égale).
2. Ajoute des détails personnels concrets : nomme des projets, des équipes, des
   outils **tirés du CV fourni**, avec leur contexte — sans rien inventer. Donne
   du contexte aux chiffres au lieu de les laisser isolés.
3. Supprime les adjectifs vagues (« passionné », « innovant », « scalable »,
   « réalisations concrètes »…) : remplace-les par des faits.
4. Ajoute une touche émotionnelle : par exemple « Ce qui m'a vraiment plu dans
   votre offre, c'est… », une réaction sincère à l'offre ou au poste.
5. Termine par une phrase naturelle : par exemple « J'espère que mon profil
   pourra vous intéresser » — et non « Je serais ravi d'échanger ». Conserve la
   formule de politesse finale (« Cordialement, »), sans signature ni coordonnées.
6. Interdits : formules toutes faites, ton corporate impersonnel, en-tête de
   coordonnées, placeholders en fin de lettre.
7. Ne PAS inventer de compétences, d'expériences, de formations, de chiffres ou
   de réalisations absents du CV fourni.
8. Objet de la lettre doit être professionnel, neutre, sans effet de style. Juste l'essentiel.
9. Lettre courte (moins de 200 mots)
10. Réponds UNIQUEMENT en Markdown, sans blocs de code ni texte autour.
"""


def _build_prompt(
    job: Dict[str, Any], profile: Dict[str, Any]
) -> str:
    """Construit le prompt utilisateur (offre, CV anonymisé).

    Aucune troncature : le CV doit être transmis intégralement pour que la
    lettre s'appuie sur tous les faits du candidat.
    """

    logger.debug(f"profile envoyé au LLM pour la lettre : {profile}")

    return USER_PROMPT_TEMPLATE.format(
        JOB_MARKER=JOB_MARKER,
        PROFILE_MARKER=PROFILE_MARKER,
        LETTER_MARKER=LETTER_MARKER,
        job=json.dumps(job, ensure_ascii=False, default=str),
        profile=json.dumps(profile, ensure_ascii=False, default=str),
    )


def _build_rewrite_prompt(
    job: Dict[str, Any], profile: Dict[str, Any], first_letter: str
) -> str:
    """Construit le prompt de réécriture (1re lettre + offre + CV anonymisé).

    Le CV est transmis pour que la réécriture puisse nommer projets, équipes et
    outils réels — sans rien inventer. Aucune troncature.
    """
    return REWRITE_USER_PROMPT_TEMPLATE.format(
        FIRST_LETTER_MARKER=FIRST_LETTER_MARKER,
        first_letter=first_letter,
        JOB_MARKER=JOB_MARKER,
        job=json.dumps(job, ensure_ascii=False, default=str),
        PROFILE_MARKER=PROFILE_MARKER,
        profile=json.dumps(profile, ensure_ascii=False, default=str),
        REWRITE_MARKER=REWRITE_MARKER,
    )


def generate_letter_markdown(
    job: Dict[str, Any], profile: Dict[str, Any]
) -> str:
    """Génère une lettre de motivation en Markdown pour l'offre donnée.

    Args:
        job: dict de l'offre (``build_score_job``).
        profile: dict du profil, dont la clé ``raw_cv`` = CV (généré ou brut)
            markdown anonymisé.

    Returns:
        Le Markdown de la lettre de motivation.

    Raises:
        LetterGenerationError: si la clé API est absente, l'appel échoue ou la
            réponse est vide/invalide (pas de fallback).
    """
    llm = score_engine.GENERATION_LLM
    if llm is None:
        logger.error("MISTRAL_API_KEY absente : génération de lettre LLM indisponible.")
        raise LetterGenerationError(
            "MISTRAL_API_KEY absente : génération de lettre de motivation LLM indisponible."
        )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=_build_prompt(job, profile)),
    ]

    try:
        response = llm.invoke(messages)
        markdown = _strip_code_fences(response.content)
        if not markdown.strip():
            raise LetterGenerationError("Génération de lettre : réponse LLM vide")
        return markdown
    except LetterGenerationError:
        raise
    except Exception as exc:
        logger.error("Génération de lettre : erreur API : %s", exc)
        raise LetterGenerationError(
            f"Génération de lettre : erreur API ({type(exc).__name__})"
        ) from exc


def _rewrite_letter_human(
    job: Dict[str, Any], profile: Dict[str, Any], first_letter: str
) -> str:
    """Réécrit la 1re lettre avec un style humain, à partir des faits du CV.

    Raises:
        LetterGenerationError: si le LLM est indisponible, l'appel échoue ou la
            réponse est vide — même comportement que la pass 1.
    """
    llm = score_engine.HUMANIZE_LLM
    if llm is None:
        logger.error(
            "MISTRAL_API_KEY absente : réécriture humanisée de la lettre indisponible."
        )
        raise LetterGenerationError(
            "MISTRAL_API_KEY absente : réécriture humanisée de la lettre indisponible."
        )

    messages = [
        SystemMessage(content=REWRITE_SYSTEM_PROMPT),
        HumanMessage(content=_build_rewrite_prompt(job, profile, first_letter)),
    ]

    try:
        response = llm.invoke(messages)
        markdown = _strip_code_fences(response.content)
        if not markdown.strip():
            raise LetterGenerationError("Réécriture de lettre : réponse LLM vide")
        return markdown
    except LetterGenerationError:
        raise
    except Exception as exc:
        logger.error("Réécriture de lettre : erreur API : %s", exc)
        raise LetterGenerationError(
            f"Réécriture de lettre : erreur API ({type(exc).__name__})"
        ) from exc


def humanize_letter_markdown(
    job: Dict[str, Any], profile: Dict[str, Any]
) -> str:
    """Génère une lettre de motivation en **deux passes**.

    Pass 1 : rédaction actuelle (``generate_letter_markdown``, inchangée).
    Pass 2 (best-effort) : le LLM réécrit systématiquement la lettre de la
    pass 1 avec un style humain (``_rewrite_letter_human``). En cas d'échec de
    la pass 2, la lettre de la pass 1 est conservée.

    Raises:
        LetterGenerationError: si la pass 1 échoue (clé absente, erreur API,
            réponse vide) — la lettre n'existe pas sans la pass 1.
    """
    first = generate_letter_markdown(job, profile)

    try:
        logger.info("Pass 2 : réécriture humanisée de la lettre.")
        return _rewrite_letter_human(job, profile, first)
    except LetterGenerationError as exc:
        logger.warning(
            "Réécriture humanisée en échec (%s) : lettre pass 1 conservée.", exc
        )
        return first
