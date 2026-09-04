"""Extraction de compétences (LLM) et utilitaires partagés du scoring.

Le scoring offre / profil vit désormais dans ``llm_matcher.py`` (LLM Mistral).
Ce module conserve : ``extract_skills`` (extraction LLM à l'ingestion), ses
helpers de normalisation (``normalize_text``, ``skills_to_names``),
``offer_skills``, l'instance ``LLM`` du matching, ``GENERATION_LLM`` (instance
dédiée, à plus grand budget de tokens, pour la pass 1 de la **lettre**),
``CV_GENERATION_LLM`` (instance dédiée à la pass 1 de la **génération de CV**),
``HUMANIZE_LLM`` (instance dédiée de la **pass 2** — réécriture humanisée — de
la lettre) et ``URL_SCRAPER_LLM`` (instance dédiée à l'extraction d'une offre
d'emploi depuis le texte d'une page web).

Toutes les instances pointent actuellement sur ``ministral-14b-latest``
(repli choisi le 2026-09-04) : sur le plan gratuit du workspace,
``mistral-small`` a son enveloppe mensuelle épuisée (HTTP 429) et
``mistral-large`` n'est pas provisionné (HTTP 403 ``tier_not_allowed``).
À réévaluer au reset mensuel ou au passage sur un plan payant.
"""

import json
import os
import re
from typing import Any, Dict, List

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mistralai import ChatMistralAI

from config.logger_config import setup_logging
from src.config.settings import PROJECT_ROOT

logger = setup_logging(__name__)

# Charge .env avant de lire la clé API (défaut : racine du projet).
load_dotenv(PROJECT_ROOT / ".env")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
# 2026-09-04 : repli sur ministral-14b-latest — mistral-small (plan gratuit) a
# son enveloppe mensuelle épuisée (HTTP 429). À rétablir au reset / plan payant.
LLM_MODEL = "ministral-14b-latest"
TEMPERATURE = 0.1
MAX_TOKEN = 2000

# LLM None si pas de clé : extract_skills renvoie alors un résultat vide
# au lieu de crasher à l'import ou à l'appel.
LLM = (
    ChatMistralAI(
        model=LLM_MODEL,
        api_key=MISTRAL_API_KEY,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKEN,
    )
    if MISTRAL_API_KEY
    else None
)

# Instance dédiée à la génération de CV : un CV reformulé dépasse facilement
# les 2000 tokens du matching (max_tokens de LLM). Température légèrement plus
# haute pour une rédaction fluide, sans dériver de l'extraction/matching.
GENERATION_MAX_TOKEN = 4096
GENERATION_TEMPERATURE = 0.2

GENERATION_LLM = (
    ChatMistralAI(
        model=LLM_MODEL,
        api_key=MISTRAL_API_KEY,
        temperature=GENERATION_TEMPERATURE,
        max_tokens=GENERATION_MAX_TOKEN,
    )
    if MISTRAL_API_KEY
    else None
)

# Instance dédiée à la **pass 1 de la génération de CV** : indépendante de la
# lettre (``GENERATION_LLM``). Sur **mistral-large-latest** à l'origine (choisi
# pour la qualité de recomposition), mais ce modèle n'est pas provisionné sur le
# plan gratuit (HTTP 403 ``tier_not_allowed``) → repli 2026-09-04 sur
# ministral-14b-latest. Budget de tokens et température identiques à la
# génération (un CV recomposé ≈ un document).
CV_GENERATION_MODEL = "ministral-14b-latest"

CV_GENERATION_LLM = (
    ChatMistralAI(
        model=CV_GENERATION_MODEL,
        api_key=MISTRAL_API_KEY,
        temperature=GENERATION_TEMPERATURE,
        max_tokens=GENERATION_MAX_TOKEN,
    )
    if MISTRAL_API_KEY
    else None
)

# Pass 2 de la lettre de motivation (réécriture humanisée) : indépendante du
# modèle de génération de la lettre (``GENERATION_LLM``). Sur
# **mistral-large-latest** à l'origine, non provisionné sur le plan gratuit
# (HTTP 403) → repli 2026-09-04 sur ministral-14b-latest. Budget de tokens et
# température identiques à la génération (une réécriture ≈ un document).
HUMANIZE_MODEL = "ministral-14b-latest"

HUMANIZE_LLM = (
    ChatMistralAI(
        model=HUMANIZE_MODEL,
        api_key=MISTRAL_API_KEY,
        temperature=GENERATION_TEMPERATURE,
        max_tokens=GENERATION_MAX_TOKEN,
    )
    if MISTRAL_API_KEY
    else None
)

# Instance dédiée à l'extraction d'une offre d'emploi depuis le texte d'une
# page web (feature « Ajouter des offres d'emploi ») : suit ``LLM_MODEL``
# (ministral-14b-latest, repli — voir module docstring), température
# d'extraction factuelle (0.1). Budget de sortie généreux : la
# sortie d'une **liste** reproduit les URLs des offres, et certaines pages (ex.
# Indeed, URLs de tracking ``pagead/clk``) portent des URLs de ~350-500
# caractères — 50 URLs ≈ 18 k caractères ≈ ~13 k tokens, au-delà du budget
# historique (3000). ``max_tokens`` est un **plafond**, pas une injonction : la
# sortie réelle reste proportionnelle au nombre d'URLs demandées (borné par le
# service à 2 × ``max_offers``), le budget ne fait que laisser le modèle finir.
# Couvre aussi les descriptions complètes d'offres uniques sans troncature.
URL_SCRAPER_MODEL = LLM_MODEL  # ministral-14b-latest (repli, voir module docstring)
URL_SCRAPER_MAX_TOKEN = 16000

URL_SCRAPER_LLM = (
    ChatMistralAI(
        model=URL_SCRAPER_MODEL,
        api_key=MISTRAL_API_KEY,
        temperature=TEMPERATURE,
        max_tokens=URL_SCRAPER_MAX_TOKEN,
    )
    if MISTRAL_API_KEY
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
    if LLM is None:
        logger.warning("MISTRAL_API_KEY absente : extraction de compétences vide.")
        return {"hard_skills": [], "soft_skills": [], "certifications": []}

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
        
        return result

    except json.JSONDecodeError as e:
        logger.error("Erreur de parsing JSON : %s", e)
        logger.error("Réponse brute : %s", response_text if "response_text" in locals() else "N/A")

        return {"hard_skills": [], "soft_skills": [], "certifications": []}

    except Exception as e:
        logger.error("Erreur API : %s", e)
        
        return {"hard_skills": [], "soft_skills": [], "certifications": []}
