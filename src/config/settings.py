"""Configuration applicative centralisée.

Lit les variables d'environnement (fichier ``.env`` à la racine du projet si
présent) et le fichier ``src/config/scoring.yaml`` (seuil de génération de CV).
"""

import os
from pathlib import Path

from dotenv import load_dotenv
import yaml

# Racine du projet : src/config/settings.py -> parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")


# --- Base de données -------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://user:password@localhost:5434/job_copilot",
)


# --- Chemins de données -----------------------------------------------------
DATA_DIR = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")))
HELLOWORK_OUTPUT_DIR = DATA_DIR / "hellowork"


# --- Scraping ---------------------------------------------------------------
KEYWORD_LIST = ["data engineer"]
LOCATION_LIST = ["Île-de-France"]


# --- Matching ----------------------------------------------------------------
# Le score de compatibilité est produit par le LLM (src/core/scoring/llm_matcher.py) ;
# seul le seuil de génération de CV reste configurable (scoring.yaml).
_SCORING_CONFIG = yaml.safe_load(
    (PROJECT_ROOT / "src" / "config" / "scoring.yaml").read_text(encoding="utf-8")
)
MATCH_THRESHOLD = float(_SCORING_CONFIG.get("match_threshold", 60))
