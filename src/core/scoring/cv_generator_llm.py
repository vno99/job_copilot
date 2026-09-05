"""Génération de CV par LLM.

Le LLM **recompose** un CV existant **anonymisé** en Markdown, sans le dénaturer
: il réorganise, condense et reformule légèrement les informations **déjà
présentes** dans le CV socle afin de mettre en avant celles qui sont les plus
pertinentes pour une offre, **sans modifier les faits, le niveau de preuve,
l'identité professionnelle, les responsabilités ou le niveau d'expertise** du
candidat. Le CV socle est l'unique source de vérité ; l'offre ne sert qu'à
hiérarchiser les informations existantes.
La fidélité est aussi **sémantique** : le prompt interdit
d'augmenter la portée des informations (échelle mentionnée → utilisée →
expérience → spécialisation → expertise — la présence d'une technologie ne
prouvant jamais une capacité ni l'agrégation non documentée de technologies en
une capacité ou architecture nouvelle), le résumé doit rester justifiable par
le CV et pas plus ambitieux que le résumé source, le CV ne démontre pas la
pertinence d'une compétence pour l'offre (aucun lien argumentatif non
documenté), le matching ne sert qu'à hiérarchiser et le titre ne peut être
recomposé que s'il reste factuellement compatible avec le parcours. Le CV n'est **jamais tronqué**
(contrairement au matching) : la mise en forme doit arriver intacte au LLM. Les
coordonnées réelles ne sont pas transmises — le serveur les réinjecte ensuite
(``privacy.anonymize.inject_contact_info``).

La génération se fait en **une passe** (``humanize_cv_markdown``) :
``generate_cv_markdown`` recompose le CV sur ``CV_GENERATION_LLM``
(mistral-large-latest via OpenRouter — qualité de recomposition). La pass 2
(``_rewrite_cv_human``, réécriture « humaine » sur ``HUMANIZE_LLM``) est
**désactivée** : ses prompts ``REWRITE_*`` et le code sont conservés pour un
usage futur, mais ne sont plus appelés.

La pass 1 **exige** le LLM : sans clé ou en cas de réponse vide/invalide,
``generate_cv_markdown`` lève ``CVGenerationError`` (→ HTTP 502), pas de
fallback.
"""

import json
import re
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage

from config.logger_config import setup_logging
from src.core.scoring import score_engine
from src.core.scoring.llm_matcher import JOB_MARKER, PROFILE_MARKER, _strip_code_fences

logger = setup_logging(__name__)

# Marqueur dédié au prompt de génération, utilisé par le mock du conftest pour
# distinguer la génération du matching (les deux contiennent PROFIL_MARKER).
COMPATIBILITY_MARKER = "=== ANALYSE DE COMPATIBILITÉ ==="

# Marqueur de la pass 2 (réécriture « humaine »). Le prompt de réécriture
# contient aussi COMPATIBILITY_MARKER et PROFIL_MARKER (offre, CV anonymisé et
# matching transmis) : le mock du conftest le teste AVANT la génération pass 1,
# distingué par CV_REWRITE_MARKER. Il ne contient pas le marqueur de lettre
# (le mock ne servirait pas une lettre) ; le CV de la pass 1 y est délimité par
# FIRST_CV_MARKER.
CV_REWRITE_MARKER = "=== RÉÉCRITURE HUMAINE CV ==="
FIRST_CV_MARKER = "=== CV INITIAL ==="


class CVGenerationError(RuntimeError):
    """Le LLM est indisponible (clé absente, erreur API, réponse vide/invalide)."""


SYSTEM_PROMPT = """Tu es un expert en rédaction de CV techniques pour le marché francophone.

Tu reçois un CV anonymisé — l'UNIQUE SOURCE DE VÉRITÉ — ainsi qu'une offre
d'emploi et son matching. Tu dois RECOMPOSER ce CV : réorganiser, condenser et
reformuler légèrement les informations déjà présentes pour donner plus de
visibilité à celles qui sont pertinentes pour l'offre, sans rien inventer ni
gonfler.

==================================================
1. FIDÉLITÉ — RÈGLE ABSOLUE
==================================================

Toute affirmation de la sortie doit être une reformulation d'une information
explicite du CV source, au même niveau ou à un niveau plus faible.

En pratique :
- les mots techniques et le vocabulaire métier viennent du CV source, jamais de
  l'offre (une technologie du CV peut être mise en avant, un mot de l'offre
  absent du CV ne peut pas apparaître) ;
- aucune compétence, expertise, responsabilité, chiffre, date, projet ou
  expérience ne peut être créé ;
- aucun niveau de preuve ne peut être augmenté (mention → utilisation →
  expérience → spécialisation → expertise) ;
- la présence de plusieurs technologies ne prouve pas une capacité commune
  (ex. « Python + Airflow » ne crée pas « industrialisation de pipelines »).

Quand une formulation exacte du CV source fonctionne, garde-la. En cas
d'hésitation, choisis la formulation la plus proche du CV.

==================================================
2. VISIBILITÉ — L'OBJECTIF
==================================================

L'offre et le matching servent uniquement à classer les informations existantes
: quoi présenter en premier, quoi rendre plus visible, quoi condenser.
Ils ne créent jamais d'information.

==================================================
3. PORTÉE — LES LIMITES DU MOUVEMENT
==================================================

Tu peux : réordonner, condenser, reformuler, changer l'ordre des rubriques, des
compétences, des projets et des expériences, déplacer un fait vers une position
plus visible.

Tu ne peux pas : supprimer une expérience ou un projet, changer l'identité
professionnelle, modifier les dates, ajouter une section ou des coordonnées
(placeholders [NOM], [EMAIL]… intouchables).

==================================================
4. SORTIE
==================================================

Conserve la structure générale du CV source (rubriques, listes, tableaux ;
chaque rangée de tableau sur sa propre ligne). Réponds UNIQUEMENT avec le CV
recomposé en Markdown, sans bloc de code ni texte autour.
"""


USER_PROMPT_TEMPLATE = """
Recompose le CV source en fonction de l'offre d'emploi.

Il s'agit d'une recomposition de la présentation, et non d'une adaptation du
profil : l'offre sert uniquement à hiérarchiser les informations déjà présentes
dans le CV source.

{JOB_MARKER}
{job}

{PROFILE_MARKER}
{profile}

{RELEVANCE_MARKER}
{match}

Le CV source est la seule source de vérité concernant le candidat.
Le classement de pertinence sert uniquement à prioriser les informations
existantes.

Applique strictement les règles de recomposition définies dans le
SYSTEM_PROMPT.

Réponds uniquement avec le CV recomposé en Markdown.
"""


REWRITE_USER_PROMPT_TEMPLATE = """
Reformule le CV adapté ci-dessous afin qu'il sonne naturel, professionnel et
crédible, tout en conservant sa pertinence par rapport à l'offre.

{CV_REWRITE_MARKER}

====================
CV ADAPTÉ — CONTENU À RÉÉCRIRE
==============================

{FIRST_CV_MARKER}
{first_cv}

Le CV ci-dessus est le résultat de la première passe.

Il constitue la source prioritaire pour déterminer QUEL CONTENU doit apparaître
dans le CV final.

Ne réintroduis pas une information absente de ce CV uniquement parce qu'elle
figure dans le profil original.

====================
CV ORIGINAL — RÉFÉRENCE
=======================

{PROFILE_MARKER}
{profile}

Le profil ci-dessus est le CV original anonymisé complet du candidat en
Markdown.

Il sert à :

* vérifier les faits présents dans le CV adapté ;
* préserver les formulations ou informations lorsqu'elles sont nécessaires ;
* reproduire la structure et les conventions de mise en forme du CV original.

Il ne sert PAS à réintroduire dans le CV final des informations que la
première passe a volontairement supprimées, réduites ou écartées.

====================
OFFRE
=====

{JOB_MARKER}
{job}

L'offre sert uniquement de contexte pour vérifier que la réécriture reste
cohérente avec le positionnement déjà établi par la première passe.

====================
MATCHING
========

{COMPATIBILITY_MARKER}
{match}

Le matching a été réalisé avant la génération.

Il sert uniquement de contexte de pertinence.

Il ne constitue jamais une source de nouvelles informations concernant le
candidat.

====================
RÈGLE DE PRIORITÉ
=================

Pour le contenu :
FIRST_CV est prioritaire.

Pour les faits :
PROFILE permet uniquement de vérifier FIRST_CV.

Pour la structure et la mise en forme :
PROFILE sert de référence.

Pour la pertinence :
JOB + MATCH fournissent le contexte.

La deuxième passe ne doit pas refaire l'adaptation réalisée par la première.

====================
FIDÉLITÉ FACTUELLE — PRIORITÉ ABSOLUE
=====================================

1. Chaque affirmation du CV final doit être directement justifiable par
   FIRST_CV et/ou PROFILE.

2. N'ajoute aucune information simplement parce qu'elle apparaît dans JOB ou
   MATCH.

3. N'ajoute aucune compétence, technologie, outil, méthodologie, expérience,
   formation, certification ou responsabilité.

4. Ne crée aucun chiffre, pourcentage, durée, date ou résultat.

5. Ne crée aucun impact business qui n'est pas documenté.

6. Ne crée aucun problème, contrainte, difficulté technique, motivation ou
   contexte métier absent du CV.

7. Si FIRST_CV décrit une tâche sans résultat, conserve cette réalité.

8. Si FIRST_CV décrit une contribution sans responsabilité de pilotage,
   conserve ce niveau de responsabilité.

9. Préserve exactement le niveau de responsabilité exprimé.

Ne transforme jamais :

* « participation à » en « pilotage de » ;
* « contribution à » en « conception de » ;
* « utilisation de » en « expertise de » ;
* « connaissance de » en « maîtrise de » ;
* « développement de » en « architecture de » ;
* « support de » en « responsabilité de » ;
* « collaboration avec » en « management de ».

10. Une reformulation stylistique ne doit jamais augmenter le niveau
    d'expertise ou de responsabilité.

====================
HUMANISATION
============

11. Supprime les formulations mécaniques et répétitives.

12. Varie naturellement la longueur des phrases.

13. Évite de commencer toutes les puces avec exactement la même construction.

14. Utilise des verbes d'action précis et naturels.

15. Privilégie un style sobre, concret et professionnel.

16. Évite les adjectifs vagues et les formulations marketing.

17. Évite les phrases toutes faites.

18. Ne cherche pas à rendre le texte artificiellement original.

19. Ne transforme pas systématiquement les missions en paragraphes narratifs.

20. Ne fabrique jamais de storytelling.

21. Ne crée pas artificiellement une structure :
    problème → solution → résultat
    lorsque ces éléments ne sont pas explicitement présents.

22. Conserve les détails techniques utiles présents dans FIRST_CV.

23. Supprime les répétitions uniquement lorsqu'elles n'entraînent aucune perte
    d'information.

24. Le résultat doit ressembler à un CV rédigé par un professionnel technique,
    pas à un texte marketing ni à une démonstration de style.

====================
RÉSUMÉ
======

25. Si FIRST_CV contient un résumé, améliore sa formulation et sa lisibilité.

26. Le résumé doit rester entièrement justifiable à partir de FIRST_CV et
    PROFILE.

27. N'ajoute aucune promesse, compétence, responsabilité ou réalisation.

====================
STRUCTURE ET MISE EN FORME
==========================

28. Reproduis autant que possible la structure et la mise en forme du PROFILE.

29. Conserve les conventions de titres, sous-titres, listes et tableaux du CV
    original.

30. Le contenu final doit toutefois suivre FIRST_CV.

31. Si FIRST_CV a supprimé une expérience ou une compétence présente dans
    PROFILE, ne la réintroduis pas.

32. Si FIRST_CV a réorganisé des expériences, conserve cette nouvelle
    organisation.

33. Si PROFILE contient un tableau Markdown, respecte sa structure lorsque
    cette section existe encore dans FIRST_CV.

34. Chaque rangée d'un tableau Markdown doit être sur sa propre ligne.

35. N'ajoute pas de nouvelle section uniquement pour rendre le CV plus
    professionnel.

====================
COORDONNÉES
===========

36. Ne génère aucun nom, téléphone, email, adresse ou LinkedIn.

37. Ne crée aucun nouveau placeholder.

38. Les coordonnées seront réinjectées par le serveur.

====================
SORTIE
======

39. Retourne uniquement le CV final en Markdown.

40. Ne retourne aucune explication, note, analyse, score ou commentaire hors
    CV.

41. N'utilise aucun bloc de code Markdown.
"""


def _build_prompt(
    job: Dict[str, Any], profile: Dict[str, Any], match: Dict[str, Any]
) -> str:
    """Construit le prompt utilisateur (offre, CV anonymisé, analyse).

    Aucune troncature (contrairement à ``llm_matcher._build_prompt``) : le CV
    doit être transmis intégralement pour que sa mise en forme soit conservée.
    """

    logger.debug(f"profile envoye au LLM pour le CV Gen : {profile}")

    return USER_PROMPT_TEMPLATE.format(
        JOB_MARKER=JOB_MARKER,
        PROFILE_MARKER=PROFILE_MARKER,
        RELEVANCE_MARKER=COMPATIBILITY_MARKER,
        job=json.dumps(job, ensure_ascii=False, default=str),
        profile=json.dumps(profile, ensure_ascii=False, default=str),
        match=json.dumps(match, ensure_ascii=False, default=str),
    )


def _split_collapsed_table_rows(markdown: str) -> str:
    """Répare les tableaux GFM dont les rangées sont collées sur une seule ligne.

    Le LLM omet parfois les sauts de ligne entre les rangées d'un tableau
    (``| a | b | | c | d |``) : sans newline, remark-gfm ne le rend pas comme
    tableau. Sur une ligne commençant par ``|``, un ``| |`` (fin de rangée +
    début de la rangée suivante) signale un collage : on insère un saut de ligne
    à cet endroit (``| |`` → ``|\n|``). La rangée de séparation
    (``|----|----|``) est préservée — son ``|`` suivant n'est pas précédé d'un
    espace. Les lignes qui ne commencent pas par ``|`` ne sont pas touchées.
    """
    if "| |" not in markdown:
        return markdown

    lines = markdown.split("\n")
    for i, line in enumerate(lines):
        if line.lstrip().startswith("|") and "| |" in line:
            lines[i] = re.sub(r"\|[ ]+\|", "|\n|", line)
    return "\n".join(lines)


def generate_cv_markdown(
    job: Dict[str, Any], profile: Dict[str, Any], match: Dict[str, Any]
) -> str:
    """Recompose le CV en Markdown (recomposition du CV anonymisé).

    Args:
        job: dict de l'offre (``build_score_job``).
        profile: dict du profil, dont la clé ``raw_cv`` = CV markdown anonymisé.
        match: dict du ``match_result`` (score, forces, faiblesses…).

    Returns:
        Le Markdown du CV recomposé.

    Raises:
        CVGenerationError: si la clé API est absente, l'appel échoue ou la
            réponse est vide/invalide (pas de fallback).
    """
    llm = score_engine.CV_GENERATION_LLM
    if llm is None:
        logger.error("OPENROUTER_API_KEY absente : génération de CV LLM indisponible.")
        raise CVGenerationError(
            "OPENROUTER_API_KEY absente : génération de CV LLM indisponible."
        )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=_build_prompt(job, profile, match)),
    ]

    try:
        response = llm.invoke(messages)
        markdown = _split_collapsed_table_rows(_strip_code_fences(response.content))
        if not markdown.strip():
            raise CVGenerationError("Génération de CV : réponse LLM vide")
        return markdown
    except CVGenerationError:
        raise
    except Exception as exc:
        logger.error("Génération de CV : erreur API : %s", exc)
        raise CVGenerationError(
            f"Génération de CV : erreur API ({type(exc).__name__})"
        ) from exc


def _build_rewrite_prompt(
    job: Dict[str, Any],
    profile: Dict[str, Any],
    match: Dict[str, Any],
    first_cv: str,
) -> str:
    """Construit le prompt de réécriture (1re CV + offre + CV anonymisé + matching).

    L'offre, le CV anonymisé et le matching sont transmis pour que la réécriture
    reste alignée sur le poste et **sans rien inventer**. Aucune troncature.
    """
    return REWRITE_USER_PROMPT_TEMPLATE.format(
        FIRST_CV_MARKER=FIRST_CV_MARKER,
        first_cv=first_cv,
        JOB_MARKER=JOB_MARKER,
        job=json.dumps(job, ensure_ascii=False, default=str),
        PROFILE_MARKER=PROFILE_MARKER,
        profile=json.dumps(profile, ensure_ascii=False, default=str),
        COMPATIBILITY_MARKER=COMPATIBILITY_MARKER,
        match=json.dumps(match, ensure_ascii=False, default=str),
        CV_REWRITE_MARKER=CV_REWRITE_MARKER,
    )


def _rewrite_cv_human(
    job: Dict[str, Any],
    profile: Dict[str, Any],
    match: Dict[str, Any],
    first_cv: str,
) -> str:
    """Reformule le CV de la pass 1 avec un style humain, à partir des faits.

    Raises:
        CVGenerationError: si le LLM est indisponible, l'appel échoue ou la
            réponse est vide — même comportement que la pass 1.
    """
    llm = score_engine.HUMANIZE_LLM
    if llm is None:
        logger.error(
            "OPENROUTER_API_KEY absente : réécriture humanisée du CV indisponible."
        )
        raise CVGenerationError(
            "OPENROUTER_API_KEY absente : réécriture humanisée du CV indisponible."
        )

    messages = [
        SystemMessage(content=REWRITE_SYSTEM_PROMPT),
        HumanMessage(content=_build_rewrite_prompt(job, profile, match, first_cv)),
    ]

    try:
        response = llm.invoke(messages)
        markdown = _split_collapsed_table_rows(_strip_code_fences(response.content))
        if not markdown.strip():
            raise CVGenerationError("Réécriture de CV : réponse LLM vide")
        return markdown
    except CVGenerationError:
        raise
    except Exception as exc:
        logger.error("Réécriture de CV : erreur API : %s", exc)
        raise CVGenerationError(
            f"Réécriture de CV : erreur API ({type(exc).__name__})"
        ) from exc


def humanize_cv_markdown(
    job: Dict[str, Any], profile: Dict[str, Any], match: Dict[str, Any]
) -> str:
    """Recompose le CV en **une passe** (pass 2 désactivée).

    La pass 2 (``_rewrite_cv_human``) est désactivée : ses prompts ``REWRITE_*``
    et le code sont conservés pour un usage futur, mais cette fonction retourne
    directement le CV de la pass 1 (``generate_cv_markdown``).

    Raises:
        CVGenerationError: si la pass 1 échoue (clé absente, erreur API, réponse
            vide) — le CV n'existe pas sans la pass 1.
    """
    return generate_cv_markdown(job, profile, match)
