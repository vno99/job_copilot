"""Extraction de compétences (LLM) et utilitaires partagés du scoring.

Le scoring offre / profil vit désormais dans ``llm_matcher.py`` (LLM Mistral via OpenRouter).
Ce module conserve : ``extract_skills`` (extraction LLM à l'ingestion), ses
helpers de normalisation (``normalize_text``, ``skills_to_names``),
``offer_skills``, l'instance ``LLM`` du matching, ``GENERATION_LLM`` (instance
dédiée, à plus grand budget de tokens, pour la pass 1 de la **lettre**),
``CV_GENERATION_LLM`` (instance dédiée à la pass 1 de la **génération de CV**),
``HUMANIZE_LLM`` (instance dédiée de la **pass 2** — réécriture humanisée — de
la lettre) et ``URL_SCRAPER_LLM`` (instance dédiée à l'extraction d'une offre
d'emploi depuis le texte d'une page web).

Toutes les instances utilisent OpenRouter (``ChatOpenAI`` avec
``openai_api_base=https://openrouter.ai/api/v1``).

Modèles configurables via variables d'environnement :
- ``OPENROUTER_LLM_MODEL_SMALL`` (défaut : ``mistral/mistral-small-latest``) —
  extraction, matching, génération de lettre pass 1 (rapide, économique) ;
- ``OPENROUTER_LLM_MODEL_LARGE`` (défaut : ``mistral/mistral-large-latest``) —
  génération de CV et réécriture humanisée de la lettre (qualité de rédaction).
"""

import json
import os
import re
from typing import Any, Dict, List

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.logger_config import setup_logging
from src.config.settings import PROJECT_ROOT

logger = setup_logging(__name__)

# Charge .env avant de lire la clé API (défaut : racine du projet).
load_dotenv(PROJECT_ROOT / ".env")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_BASE = os.getenv("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")

# Modèles OpenRouter — configurables via variables d'environnement.
# Modèle par défaut : "mistral/mistral-small-latest" (extraction, matching, lettre pass 1).
OPENROUTER_LLM_MODEL_SMALL = os.getenv(
    "OPENROUTER_LLM_MODEL_SMALL", "mistral/mistral-small-latest"
)
# Modèle par défaut : "mistral/mistral-large-latest" (génération CV, réécriture lettre).
OPENROUTER_LLM_MODEL_LARGE = os.getenv(
    "OPENROUTER_LLM_MODEL_LARGE", "mistral/mistral-large-latest"
)

LLM_MODEL = OPENROUTER_LLM_MODEL_SMALL
TEMPERATURE = 0.1
MAX_TOKEN = 2000

# LLM None si pas de clé : extract_skills renvoie alors un résultat vide
# au lieu de crasher à l'import ou à l'appel.
LLM = (
    ChatOpenAI(
        model=LLM_MODEL,
        api_key=OPENROUTER_API_KEY,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKEN,
        openai_api_base=OPENROUTER_API_BASE,
    )
    if OPENROUTER_API_KEY
    else None
)

# Instance dédiée à la génération de CV : un CV reformulé dépasse facilement
# les 2000 tokens du matching (max_tokens de LLM). Température légèrement plus
# haute pour une rédaction fluide, sans dériver de l'extraction/matching.
GENERATION_MAX_TOKEN = 4096
GENERATION_TEMPERATURE = 0.2

GENERATION_LLM = (
    ChatOpenAI(
        model=LLM_MODEL,
        api_key=OPENROUTER_API_KEY,
        temperature=GENERATION_TEMPERATURE,
        max_tokens=GENERATION_MAX_TOKEN,
        openai_api_base=OPENROUTER_API_BASE,
    )
    if OPENROUTER_API_KEY
    else None
)

# Instance dédiée à la **pass 1 de la génération de CV** : indépendante de la
# lettre (``GENERATION_LLM``). Sur **mistral-large-latest** (qualité de
# recomposition supérieure pour les longs documents).
CV_GENERATION_MODEL = OPENROUTER_LLM_MODEL_LARGE

CV_GENERATION_LLM = (
    ChatOpenAI(
        model=CV_GENERATION_MODEL,
        api_key=OPENROUTER_API_KEY,
        temperature=GENERATION_TEMPERATURE,
        max_tokens=GENERATION_MAX_TOKEN,
        openai_api_base=OPENROUTER_API_BASE,
    )
    if OPENROUTER_API_KEY
    else None
)

# Pass 2 de la lettre de motivation (réécriture humanisée) : indépendante du
# modèle de génération de la lettre (``GENERATION_LLM``). Sur
# **mistral-large-latest** pour la meilleure qualité de réécriture.
HUMANIZE_MODEL = OPENROUTER_LLM_MODEL_LARGE

HUMANIZE_LLM = (
    ChatOpenAI(
        model=HUMANIZE_MODEL,
        api_key=OPENROUTER_API_KEY,
        temperature=GENERATION_TEMPERATURE,
        max_tokens=GENERATION_MAX_TOKEN,
        openai_api_base=OPENROUTER_API_BASE,
    )
    if OPENROUTER_API_KEY
    else None
)

# Instance dédiée à l'extraction d'une offre d'emploi depuis le texte d'une
# page web (feature « Ajouter des offres d'emploi ») : suit ``LLM_MODEL``
# (mistral-small-latest, rapide), température d'extraction factuelle (0.1).
# Budget de sortie généreux : la sortie d'une **liste** reproduit les URLs des
# offres, et certaines pages (ex. Indeed, URLs de tracking ``pagead/clk``) portent
# des URLs de ~350-500 caractères — 50 URLs ≈ 18 k caractères ≈ ~13 k tokens,
# au-delà du budget historique (3000). ``max_tokens`` est un **plafond**, pas
# une injonction : la sortie réelle reste proportionnelle au nombre d'URLs
# demandées (borné par le service à 2 × ``max_offers``), le budget ne fait que
# laisser le modèle finir. Couvre aussi les descriptions complètes d'offres
# uniques sans troncature.
URL_SCRAPER_MODEL = LLM_MODEL  # OPENROUTER_LLM_MODEL_SMALL
URL_SCRAPER_MAX_TOKEN = 16000

URL_SCRAPER_LLM = (
    ChatOpenAI(
        model=URL_SCRAPER_MODEL,
        api_key=OPENROUTER_API_KEY,
        temperature=TEMPERATURE,
        max_tokens=URL_SCRAPER_MAX_TOKEN,
        openai_api_base=OPENROUTER_API_BASE,
    )
    if OPENROUTER_API_KEY
    else None
)

SYSTEM_PROMPT = """
Tu es un expert en analyse d'offres d'emploi technique.
Ta mission est d'extraire avec précision les compétences demandées.
Réponds UNIQUEMENT en JSON valide, sans texte autour.
"""

USER_PROMPT_TEMPLATE = """
Analyse l'offre d'emploi suivante et extrait UNIQUEMENT les compétences explicitement mentionnées.

RÈGLES STRICTES :
1. Ne PAS inventer de compétences. Si ce n'est pas écrit textuellement, tu ne le mets pas.
2. Pour chaque compétence, indique :
   - "name" : le nom exact de la compétence (ex: "Python", "Django", "Gestion de projet")
   - "category" : parmi ["langage", "framework", "cloud", "data", "methodologie", "soft_skill", "autre"]
   - "level" : parmi ["expert", "maîtrise", "notion", "non précisé"] 
     (déduis le niveau des mots comme "maîtriser", "connaître", "avoir des bases", "expérimenté")
   - "mandatory" : true si l'offre dit "obligatoire", "impératif", "requis" ; false sinon

3. Si l'offre mentionne des certifications, ajoute-les avec category "certification".

4. Réponds UNIQUEMENT en JSON, sans texte autour.

OFFRE À ANALYSER :
{job_description}

JSON ATTENDU (exemple) :
{{
  "hard_skills": [
    {{"name": "Python", "category": "langage", "level": "expert", "mandatory": true}},
    {{"name": "Django", "category": "framework", "level": "maîtrise", "mandatory": false}}
  ],
  "soft_skills": [
    {{"name": "Travail en équipe", "category": "soft_skill", "level": "non précisé", "mandatory": true}}
  ],
  "certifications": [
    {{"name": "AWS Certified Developer", "mandatory": false}}
  ]
}}
"""


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def skills_to_names(skills: Dict[str, Any] | None) -> List[str]:
    """Aplatit le résultat structuré de ``extract_skills`` (LLM) en liste de noms.

    Ne conserve que ``hard_skills`` et ``soft_skills`` (les certifications sont
    exclues du matching), normalisés et dédoublonnés — contrat identique à
    l'ancienne whitelist (noms en minuscules) pour le scoring et le CV.
    """
    skills = skills or {}
    names: List[str] = []
    for group in ("hard_skills", "soft_skills"):
        for item in skills.get(group, []) or []:
            name = item.get("name") if isinstance(item, dict) else item
            norm = normalize_text(name)
            if norm and norm not in names:
                names.append(norm)
    return names


def offer_skills(offer: Dict[str, Any]) -> List[str]:
    """Compétences requises d'une offre, normalisées (liste de noms).

    Priorité au ``skills_extracted`` stocké en base : l'extraction LLM n'est
    faite qu'une seule fois, à l'ingestion. L'extraction à la volée ne sert que
    de fallback quand la colonne n'est pas peuplée (offre sans ingestion, tests).
    """
    stored = offer.get("skills_extracted")
    if stored is not None:
        return skills_to_names(stored)
    return skills_to_names(extract_skills(offer.get("description") or ""))


def extract_skills(offer_text: str) -> dict:
    """Extrait les compétences d'une offre d'emploi via LLM.

    Le résultat porte un champ ``_status`` (``"disabled"``, ``"failed"``,
    ``"empty"`` ou ``"extracted"``) qui distingue un LLM désactivé / en
    échec / une offre sans compétence détectée d'une extraction **réussie**
    mais sans compétence. Le matching, le scoring et le front peuvent
    s'appuyer dessus pour ne pas traiter « LLM en panne » comme « le candidat
    n'a aucune des compétences attendues ». Le préfixe ``_`` évite la collision
    avec une éventuelle compétence nommée « status ».

    Forme de retour (toutes les branches) :

    .. code-block:: python

        {
            "hard_skills":     [{"name": "Python", ...}, ...],
            "soft_skills":     [...],
            "certifications":  [...],
            "_status":         "extracted" | "empty" | "failed" | "disabled",
        }
    """
    if LLM is None:
        logger.warning("OPENROUTER_API_KEY absente : extraction de compétences vide.")
        return {
            "hard_skills": [], "soft_skills": [], "certifications": [],
            "_status": "disabled",
        }

    user_prompt = USER_PROMPT_TEMPLATE.format(job_description=offer_text)

    try:
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt)
        ]

        response = LLM.invoke(messages)

        # Extraction du contenu
        response_text = response.content

        # Nettoyage : parfois Mistral ajoute des backticks autour du JSON
        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]  # Enlève ```json
        if response_text.startswith("```"):
            response_text = response_text[3:]  # Enlève ```
        if response_text.endswith("```"):
            response_text = response_text[:-3]  # Enlève le ``` final

        result = json.loads(response_text)

        # Petit nettoyage : on s'assure que toutes les clés existent
        default = {"hard_skills": [], "soft_skills": [], "certifications": []}
        for key in default:
            if key not in result:
                result[key] = []

        # Distinction « extraites » vs « extraites mais aucune trouvée ». Une
        # extraction réussie avec listes vides est sémantiquement différente
        # d'un échec : l'offre ne demande aucune compétence, on ne retry pas.
        is_empty = all(not result.get(k) for k in default)
        result["_status"] = "empty" if is_empty else "extracted"
        return result

    except json.JSONDecodeError as e:
        logger.error("Erreur de parsing JSON : %s", e)
        logger.error("Réponse brute : %s", response_text if "response_text" in locals() else "N/A")

        return {
            "hard_skills": [], "soft_skills": [], "certifications": [],
            "_status": "failed",
        }

    except Exception as e:
        logger.error("Erreur API : %s", e)

        return {
            "hard_skills": [], "soft_skills": [], "certifications": [],
            "_status": "failed",
        }
