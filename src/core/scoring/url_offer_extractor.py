"""Classification d'une page web et extraction d'offres d'emploi (LLM).

Feature « Ajouter des offres d'emploi » : l'utilisateur soumet une URL, la page
est récupérée côté serveur (Playwright) puis son texte est classé par le LLM
(``extract_page``) via l'instance dédiée ``score_engine.URL_SCRAPER_LLM``
(mistral-small-latest via OpenRouter).

La page peut être :
- **une offre unique** (le cas historique) : le LLM renvoie ``page_type
  "single"`` avec le contenu complet de l'offre (``offer``) ;
- **une liste d'offres** : le LLM renvoie ``page_type "list"`` avec **les URLs
  des offres** (``urls``), pas leur contenu — chaque offre est ensuite
  récupérée individuellement (fetch Playwright + ``extract_offer``) par le
  service d'ingestion ;
- **rien d'exploitable** : ``page_type "none"`` avec une ``reason`` (→ erreur).

La classification repose sur le principe **contenu principal vs contenu
secondaire** : seul le contenu principal de la page détermine son type. Le
contenu secondaire — offres « similaires » ou « recommandées », navigation,
barre latérale, pied de page — ne détermine jamais le type de page et ne
contribue jamais à l'offre extraite (notamment à sa ``description``). C'est ce
principe (règle 0 des prompts) qui évite qu'une phrase d'une offre similaire
contamine une description extraite, sans retrait mécanique du texte.

``extract_offer`` (récupération individuelle d'une page de détail) passe en
**mode mono-offre** (``extract_page(single_only=True)``) : le prompt n'offre
pas d'option « list », pour qu'une page de détail affichant des offres
similaires ou recommandées en bas ne soit pas classée en liste (l'offre
principale serait rejetée à tort).

L'extraction **exige** le LLM : sans clé API ou en cas de réponse invalide,
``extract_page`` lève ``LLMExtractionError`` (pas de fallback). Si la page ne
semble pas être une offre d'emploi (aucune offre exploitable), elle lève
``URLScrapingError`` — l'URL est alors refusée (HTTP 422) sans être persistée.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlsplit

from langchain_core.messages import HumanMessage, SystemMessage

from config.logger_config import setup_logging
from src.core.scoring import score_engine
from src.core.scoring.llm_matcher import _strip_code_fences

logger = setup_logging(__name__)

# Marqueur dédié au prompt d'extraction, utilisé par le mock du conftest pour
# distinguer cette branche des autres prompts LLM (skills, matching, CV/lettre).
# Il ne doit figurer dans aucun autre prompt du projet.
URL_OFFER_MARKER = "=== OFFRE DEPUIS URL ==="

# Borne le texte de page envoyé au LLM (coût / latence). Le texte est tronqué
# dans ``_build_prompt``, comme ``MAX_DESCRIPTION_CHARS`` du matching. Pour une
# longue liste, le début de la page est conservé (les premières offres).
MAX_PAGE_CHARS = 12000

# Borne technique du nombre d'URLs d'offres extraites d'une liste : le LLM
# renvoie au plus cette quantité (le service filtre ensuite celles déjà en base
# avant de récupérer individuellement les nouvelles — il faut donc assez d'URLs
# pour espérer ``max_offers`` offres nouvelles).
LIST_MAX_URLS = 50


class URLScrapingError(RuntimeError):
    """L'extraction est impossible : URL invalide, fetch échoué, page sans offre
    exploitable. → HTTP 422.
    """


class LLMExtractionError(RuntimeError):
    """Le LLM d'extraction est indisponible (clé absente, erreur API, JSON
    invalide). → HTTP 502.
    """


SYSTEM_PROMPT = """
Tu es un expert en analyse d'offres d'emploi sur le marché francophone.
On te donne le texte brut d'une page web : tu identifies les offres d'emploi
qu'elle présente, s'il y en a.
Réponds UNIQUEMENT en JSON valide, sans texte autour.
"""

# Règles des champs d'une offre, partagées entre le prompt de classification
# (``USER_PROMPT_TEMPLATE``, règle 3) et le prompt mono-offre
# (``SINGLE_OFFER_USER_PROMPT_TEMPLATE``, règle 3) : une seule source de vérité.
OFFER_FIELDS_RULES = """   - "title" : intitulé exact du poste (ex. "Data Engineer H/F"),
   - "company" : nom de l'entreprise,
   - "location" : lieu du poste (ville, région),
   - "contract_type" : type de contrat (CDI, CDD, freelance...),
   - "description" : TOUT le texte de l'offre tel qu'affiché sur la page —
     missions, salaire/rémunération, avantages, horaires, conditions,
     référence — retranscrit intégralement, sans résumer ni omettre de section.
     Conserve la mise en page du texte : paragraphes et listes à puces (lignes
     « - … ») retranscrits avec leurs retours à la ligne.
     N'y copie JAMAIS de texte provenant des offres « similaires »,
   - "published_date" : date de publication au format JJ/MM/AAAA ou AAAA-MM-JJ
     (chaîne), ou null si absente,
   - "experience" : niveau d'expérience demandé (ex. "3 à 5 ans") ou null,
   - "diploma" : niveau de formation demandé (ex. "Bac +5") ou null,
   - "url" : URL absolue de la page de détail de l'offre si elle apparaît dans
     les liens de la page (section « LINKS DE LA PAGE »), sinon null."""

USER_PROMPT_TEMPLATE = """
Analyse le texte de la page web ci-dessous.

{URL_OFFER_MARKER}
{page_text}

RÈGLES STRICTES :
0. Identifie d'abord le CONTENU PRINCIPAL de la page : c'est lui seul qui
   détermine le type de page. Le contenu secondaire — menu de navigation,
   barre latérale, filtres, pied de page, offres « similaires » ou
   « recommandées », bannières — ne détermine JAMAIS le type de page et ne
   contribue JAMAIS à l'offre extraite (ni à sa description, ni à ses URLs).
1. Détecte le type de page :
   - La page de DÉTAIL d'une offre (un intitulé de poste répété en titre, une
     section « Description du poste » détaillée, des mentions « Offre n° … » /
     « Publié le … », un bouton « Postuler ») a pour contenu principal UNE
     offre → renvoie :
     {{"page_type": "single", "offer": {{champs de l'offre (voir règle 3)}}}}.
     Les offres « similaires » ou « recommandées » affichées en bas d'une page
     de détail sont du contenu secondaire : ignore-les — n'extrais ni leurs
     URLs, ni leur contenu. Une page de détail n'est jamais une liste, même si
     elle contient beaucoup de liens ou d'autres offres.
   - Une page de LISTE d'offres a pour contenu principal un ensemble de cartes
     d'offres (résultats de recherche, catalogue, index) SANS description
     d'offre complète ni section « Description du poste ». Renvoie :
     {{"page_type": "list", "offers": [{{"url": "https://…"}}, …]}}
     avec UNIQUEMENT l'URL absolue de la page de détail de chaque offre (le
     lien de la carte, qui porte le titre du poste), au plus {max_urls}, dans
     l'ordre de la page. Les liens de la page sont listés en bas (section
     « LINKS DE LA PAGE ») : choisis-y le lien de détail de chaque offre, PAS
     les liens internes (sélection, tri, navigation) ni les liens d'assets.
     Ne PAS extraire le contenu des offres d'une liste (titre, description…) :
     chaque offre sera récupérée individuellement ensuite. Une liste est
     classée « list » par SA FONCTION (un ensemble de résultats de recherche),
     pas par la quantité de liens : même si elle ne contient qu'une seule
     offre, c'est une liste.
   - Si la page n'est PAS une offre d'emploi exploitable (ni une liste d'offres :
     offre expirée ou retirée, page d'erreur, page d'accueil, contenu non
     pertinent...), renvoie EXACTEMENT :
     {{"page_type": "none", "reason": "courte explication en français (ex. \\"l'offre n'est plus disponible sur le site\\")"}}.
2. Ne PAS inventer d'informations absentes du texte : pour une offre unique,
   laisse le champ vide ou null si l'information n'apparaît pas explicitement.
3. Champs attendus de "offer" (tous optionnels sauf "title" et "description") :
{OFFER_FIELDS_RULES}
4. Ne renvoie QUE des offres complètes : pour une offre unique, ignore-la si le
   titre ou la description est vide. Réponds UNIQUEMENT en JSON valide, sans
   texte autour.

JSON ATTENDU (exemple, page d'offre unique) :
{{
  "page_type": "single",
  "offer": {{
    "title": "Data Engineer H/F",
    "company": "Acme",
    "location": "Paris - 75",
    "contract_type": "CDI",
    "description": "Conception de pipelines de données avec Python et SQL.",
    "published_date": "22/05/2026",
    "experience": "3 à 5 ans",
    "diploma": "Bac +5",
    "url": "https://example.com/offres/data-engineer"
  }}
}}

JSON ATTENDU (exemple, page de liste d'offres) :
{{
  "page_type": "list",
  "offers": [
    {{"url": "https://example.com/offres/data-engineer"}},
    {{"url": "https://example.com/offres/data-analyst"}}
  ]
}}
"""

# Prompt MONO-OFFRE, utilisé par ``extract_offer`` pour les pages de détail
# récupérées individuellement (une URL extraite d'une liste). Aucune option
# « list » : le LLM ne peut pas classer une page de détail (avec ses offres
# similaires) en liste — sinon l'offre principale serait rejetée à tort.
SINGLE_OFFER_USER_PROMPT_TEMPLATE = """
On te donne le texte brut d'une page de DÉTAIL d'une offre d'emploi : tu en
extrais l'offre principale. Les offres « similaires » ou « recommandées »
éventuellement affichées en bas de page sont secondaires : ignore-les
totalement (ni leur contenu, ni leurs URLs).

{URL_OFFER_MARKER}
{page_text}

RÈGLES STRICTES :
0. Identifie d'abord le CONTENU PRINCIPAL de la page : une page de détail a
   pour contenu principal UNE offre d'emploi. Le contenu secondaire — offres
   « similaires » ou « recommandées », menu de navigation, pied de page — ne
   détermine JAMAIS le type de page et ne contribue JAMAIS à l'offre extraite
   (ni à sa description, ni à ses URLs).
1. La page est une page de DÉTAIL d'une offre : elle contient UNE offre
   principale → renvoie :
   {{"page_type": "single", "offer": {{champs de l'offre (voir règle 3)}}}}.
   Ne renvoie JAMAIS {{"page_type": "list"}}, même si la page affiche des
   offres similaires ou recommandées, et même si elle contient beaucoup de
   liens.
2. Ne PAS inventer d'informations absentes du texte : pour l'offre principale,
   laisse le champ vide ou null si l'information n'apparaît pas explicitement.
3. Champs attendus de "offer" (tous optionnels sauf "title" et "description") :
{OFFER_FIELDS_RULES}
4. Si la page ne contient AUCUNE offre exploitable (page d'erreur, offre
   expirée ou retirée, contenu non pertinent...), renvoie EXACTEMENT :
   {{"page_type": "none", "reason": "courte explication en français"}}.
5. Ne renvoie QUE des offres complètes : ignore l'offre si le titre ou la
   description est vide. Réponds UNIQUEMENT en JSON valide, sans texte autour.

JSON ATTENDU (exemple) :
{{
  "page_type": "single",
  "offer": {{
    "title": "Data Engineer H/F",
    "company": "Acme",
    "location": "Paris - 75",
    "contract_type": "CDI",
    "description": "Conception de pipelines de données avec Python et SQL.",
    "published_date": "22/05/2026",
    "experience": "3 à 5 ans",
    "diploma": "Bac +5",
    "url": "https://example.com/offres/data-engineer"
  }}
}}
"""


@dataclass
class PageResult:
    """Résultat de la classification d'une page par le LLM.

    ``page_type`` : ``"single"`` (la page EST une offre, ``offer`` contient son
    contenu complet normalisé) ou ``"list"`` (la page liste des offres, ``urls``
    contient leurs URLs normalisées dans l'ordre de la page). Les pages sans
    offre exploitable lèvent ``URLScrapingError`` dans ``extract_page``.
    """

    page_type: Literal["single", "list"]
    offer: Optional[Dict[str, Any]] = None
    urls: List[str] = field(default_factory=list)


def _build_prompt(
    page_text: str, max_urls: int = LIST_MAX_URLS, *, single_only: bool = False
) -> str:
    """Construit le prompt utilisateur avec le texte de la page (borné).

    Le texte est borné à ``MAX_PAGE_CHARS`` (le début de la page est conservé).
    Les offres « similaires » ou « recommandées » d'une page de détail ne sont
    pas retirées mécaniquement du texte : le prompt s'appuie sur le principe
    « contenu principal vs contenu secondaire » (règle 0) pour qu'elles
    n'entrent ni dans la classification, ni dans l'offre extraite. ``max_urls``
    borne le nombre d'URLs d'une liste demandées au LLM ; le défaut
    ``LIST_MAX_URLS`` garde les appels ``_build_prompt(texte)`` valides.
    ``single_only`` sélectionne le prompt mono-offre (aucune option « list ») :
    utilisé par ``extract_offer`` pour les pages de détail récupérées
    individuellement, où une réponse « list » rejetterait l'offre principale.
    """
    if len(page_text) > MAX_PAGE_CHARS:
        page_text = page_text[:MAX_PAGE_CHARS] + "…"
    if single_only:
        return SINGLE_OFFER_USER_PROMPT_TEMPLATE.format(
            URL_OFFER_MARKER=URL_OFFER_MARKER,
            page_text=page_text,
            OFFER_FIELDS_RULES=OFFER_FIELDS_RULES,
        )
    return USER_PROMPT_TEMPLATE.format(
        URL_OFFER_MARKER=URL_OFFER_MARKER,
        page_text=page_text,
        max_urls=max_urls,
        OFFER_FIELDS_RULES=OFFER_FIELDS_RULES,
    )


def _normalize_offer_url(value: Any) -> Optional[str]:
    """Normalise l'URL individuelle d'une offre (http/https + hostname).

    Ces URLs sont stockées dans ``job_offer.url`` **et récupérées
    individuellement** par le serveur dans le chemin « liste » : la barrière
    SSRF est exercée à l'exécution (``URLScraper.fetch_text`` → ``normalize_url``
    → ``_is_private_host``) — une URL refusée est simplement ignorée. Le
    fragment est retiré pour un dédoublonnage fiable. Retourne ``None`` si
    absente ou invalide.
    """
    if not value:
        return None
    try:
        parts = urlsplit(str(value).strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return parts._replace(fragment="").geturl()


def _normalize_offer(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise une offre de la réponse LLM en structure persistable."""
    return {
        "title": str(data.get("title") or "").strip(),
        "company": str(data.get("company") or "").strip() or None,
        "location": str(data.get("location") or "").strip() or None,
        "contract_type": str(data.get("contract_type") or "").strip() or None,
        "description": str(data.get("description") or "").strip(),
        "published_date": str(data.get("published_date") or "").strip() or None,
        "experience": str(data.get("experience") or "").strip() or None,
        "diploma": data.get("diploma"),
        "url": _normalize_offer_url(data.get("url")),
        # Motif du refus quand la page n'est pas exploitable (règle 1 du
        # prompt) : remonté dans le message d'``URLScrapingError``.
        "reason": str(data.get("reason") or "").strip() or None,
    }


def _is_valid_offer(norm: Dict[str, Any]) -> bool:
    """Une offre est exploitable si son titre ET sa description sont non vides."""
    return bool(norm["title"] and norm["description"])


def _raise_not_an_offer(reason: Optional[str]) -> None:
    """Lève ``URLScrapingError`` avec la ``reason`` du LLM si elle est présente."""
    message = "La page ne semble pas contenir d'offre d'emploi exploitable"
    if reason:
        message += f" : {reason}"
    raise URLScrapingError(message)


def _parse_result(
    result: Any, max_urls: int, *, single_only: bool = False
) -> PageResult:
    """Convertit la réponse LLM en ``PageResult`` (parsing tolérant).

    Schémas acceptés :
    - ``{"page_type": "single", "offer": {...}}`` → offre complète ;
    - ``{"page_type": "list", "offers": [{"url": …}, …]}`` → URLs (dans l'ordre,
      bornées à ``max_urls``) — rejeté en mode ``single_only``. La clé des URLs
      peut être **``"offers"`` ou ``"offres"``** : le LLM écrit
      parfois la clé en français, et l'une ou l'autre est acceptée ;
    - ``{"page_type": "none", "reason": …}`` → ``URLScrapingError`` ;
    - dict d'offre unique **sans** ``page_type`` (rétro-compat : mock du conftest,
      anciens appels) → traité comme ``"single"``.

    ``single_only`` : la réponse « list » est refusée (le prompt mono-offre
    l'interdit ; une page de détail avec offres similaires ne doit pas être
    classée en liste).
    """
    if not isinstance(result, dict):
        raise LLMExtractionError("Extraction d'offre : réponse JSON non-objet")

    reason = str(result.get("reason") or "").strip() or None
    page_type = result.get("page_type")

    if page_type == "single":
        offer = _normalize_offer(result.get("offer") or {})
        if not _is_valid_offer(offer):
            _raise_not_an_offer(reason)
        return PageResult(page_type="single", offer=offer)

    if page_type == "list":
        if single_only:
            # Le prompt mono-offre interdit « list » : une réponse liste sur une
            # page de détail signifie que la page n'est pas une offre unique
            # exploitable (ou que le LLM a ignoré la consigne) → refus.
            _raise_not_an_offer(reason)
        # Le LLM écrit parfois la clé en français (« offres ») : les deux sont
        # acceptées — c'est le motif de l'erreur 422 intermittente observée.
        raw_items = result.get("offers")
        if not isinstance(raw_items, list):
            raw_items = result.get("offres")
        if not isinstance(raw_items, list):
            _raise_not_an_offer(reason)
        urls: List[str] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            url = _normalize_offer_url(item.get("url"))
            if url:
                urls.append(url)
        if not urls:
            _raise_not_an_offer(reason)
        return PageResult(page_type="list", urls=urls[:max_urls])

    if page_type == "none":
        _raise_not_an_offer(reason)

    # Sans ``page_type`` : dict d'offre unique directement (rétro-compat).
    offer = _normalize_offer(result)
    if not _is_valid_offer(offer):
        _raise_not_an_offer(reason)
    return PageResult(page_type="single", offer=offer)


def _finish_reason(response: Any) -> Optional[str]:
    """Raison d'arrêt du LLM (``finish_reason`` / ``stop_reason``), pour le
    diagnostic de troncature : ``"length"`` signifie que le budget de tokens a
    été atteint et que la réponse a été coupée."""
    metadata = getattr(response, "response_metadata", None) or {}
    if not isinstance(metadata, dict):
        return None
    return metadata.get("finish_reason") or metadata.get("stop_reason")


def _is_truncated(response: Any) -> bool:
    """La réponse LLM a-t-elle été coupée par le budget de tokens (max_tokens) ?"""
    return _finish_reason(response) in ("length", "max_tokens")


def _log_llm_json_error(response: Any, exc: json.JSONDecodeError) -> None:
    """Journalise une réponse LLM non parseable avec le contexte de diagnostic.

    Longueur de la réponse, raison d'arrêt (``finish_reason``), position de
    l'erreur et fenêtre de texte autour : cela distingue une **troncature**
    (``finish_reason=length``, la sortie a été coupée par ``max_tokens``) d'un
    JSON mal formé (ex. saut de ligne littéral dans une valeur, la réponse est
    complète mais invalide) — le message « LLM indisponible » de l'agent est
    alors trompeur sans ce détail.
    """
    content = _strip_code_fences(getattr(response, "content", "") or "")
    position = getattr(exc, "pos", None)
    if isinstance(position, int):
        window = content[max(0, position - 150) : position + 150]
    else:
        window = content[:300]
    logger.error(
        "Extraction d'offre : réponse JSON invalide%s (longueur=%d, "
        "finish_reason=%s, position=%s) — contexte : %r",
        " — tronquée" if _is_truncated(response) else "",
        len(content),
        _finish_reason(response) or "inconnu",
        position,
        window,
    )


def extract_page(
    page_text: str, max_urls: int = LIST_MAX_URLS, *, single_only: bool = False
) -> PageResult:
    """Classe une page web (offre unique, liste d'offres ou rien) via le LLM.

    La page peut être une **offre unique** (``page_type "single"``, contenu
    complet dans ``offer``) ou une **liste d'offres** (``page_type "list"``,
    URLs des offres dans ``urls``, dans l'ordre de la page). Pour une liste,
    seule l'URL de chaque offre est extraite — le contenu est récupéré
    individuellement ensuite par le service.

    ``single_only`` : sélectionne le prompt mono-offre (aucune option « list »)
    — réservé aux pages dont on sait qu'elles devraient être une offre unique
    (``extract_offer``). Une page de détail avec offres similaires n'est alors
    pas classée en liste.

    Args:
        page_text: texte brut de la page (déjà extrait du HTML).
        max_urls: nombre maximal d'URLs d'une liste à conserver (défense serveur,
            le prompt seul ne suffit pas).
        single_only: prompt mono-offre (interdit la réponse « list »).

    Returns:
        ``PageResult`` (``single`` avec ``offer``, ou ``list`` avec ``urls``).

    Raises:
        LLMExtractionError: clé API absente, erreur API ou réponse JSON invalide.
        URLScrapingError: la page ne contient aucune offre exploitable (ou une
            liste sans URL exploitable) — le message précise la ``reason``
            fournie par le LLM si elle est présente.
    """
    max_urls = max(1, int(max_urls))

    llm = score_engine.URL_SCRAPER_LLM
    if llm is None:
        logger.error("OPENROUTER_API_KEY absente : extraction d'offre indisponible.")
        raise LLMExtractionError(
            "OPENROUTER_API_KEY absente : extraction d'offre indisponible."
        )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=_build_prompt(page_text, max_urls, single_only=single_only)),
    ]

    try:
        response = llm.invoke(messages)
        result = json.loads(_strip_code_fences(response.content))
    except json.JSONDecodeError as exc:
        _log_llm_json_error(response, exc)
        raise LLMExtractionError(
            "Extraction d'offre : réponse JSON invalide"
            + (" (réponse LLM tronquée)" if _is_truncated(response) else "")
        ) from exc
    except Exception as exc:
        logger.error("Extraction d'offre : erreur API : %s", exc)
        raise LLMExtractionError(
            f"Extraction d'offre : erreur API ({type(exc).__name__})"
        ) from exc

    return _parse_result(result, max_urls, single_only=single_only)


def extract_offer(page_text: str) -> Dict[str, Any]:
    """Extrait UNE offre d'emploi structurée depuis le texte d'une page de détail.

    Utilisé par l'ingestion pour récupérer individuellement chaque offre d'une
    liste (fetch Playwright + extraction mono-offre). Le prompt mono-offre
    (``single_only``) n'offre pas d'option « list » : les offres similaires ou
    recommandées affichées en bas d'une page de détail sont ignorées. La page
    doit être une offre unique (``page_type "single"``), sinon
    ``URLScrapingError``. La signature, les champs retournés (plus ``url``,
    ``None`` si absente) et les erreurs (``LLMExtractionError`` /
    ``URLScrapingError``) sont préservés.
    """
    page = extract_page(page_text, max_urls=1, single_only=True)
    if page.page_type != "single" or page.offer is None:
        raise URLScrapingError(
            "La page ne semble pas contenir d'offre d'emploi exploitable"
        )
    return page.offer
