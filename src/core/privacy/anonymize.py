"""Anonymisation d'un CV avant envoi à un LLM externe.

Retire du texte brut d'un CV les données personnelles identifiantes : nom
(prénom + nom), numéro de téléphone, adresse email, code postal + ville et lien
LinkedIn. La version stockée en base (``raw_content``) reste intégrale — c'est
uniquement le texte transmis au LLM qui est anonymisé.

Les éléments retirés sont remplacés par des placeholders explicites
(``[NOM]``, ``[EMAIL]``…) pour que le LLM ne les confonde pas avec du contenu
manquant.

Le module sert aussi à la **génération de CV** : ``extract_contact_info``
capture les vraies coordonnées (avant anonymisation) et ``inject_contact_info``
les réinjecte dans un en-tête, côté serveur, une fois le CV généré — le LLM ne
reçoit jamais les coordonnées réelles. Pour la **lettre de motivation**, aucune
réinjection n'a lieu : ``clean_letter_markdown`` retire l'identité et les
placeholders résiduels, la lettre reste anonyme.
"""

import re

_EMAIL = "[EMAIL]"
_LINKEDIN = "[LINKEDIN]"
_PHONE = "[TÉLÉPHONE]"
_POSTAL_CITY = "[VILLE]"
_NAME = "[NOM]"

# Adresse email simple (prénom_nom@domaine.tld).
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Lien LinkedIn (URL complète, lien nu ou ancrage Markdown).
_LINKEDIN_RE = re.compile(
    r"(?:https?://(?:www\.)?|www\.)?linkedin\.com/[^\s)\]|]*",
    re.IGNORECASE,
)

# Numéro de téléphone français : national (``0X XX XX XX XX``) ou international
# (``+33``/``0033``, avec éventuellement le « 0 » conservé ou « (0) »), suivi de
# 4 groupes de 2 chiffres. Séparateurs espaces/points/tirets ou rien. Borné par
# des limites de mot pour ne pas toucher aux dates (``JJ/MM/AAAA``).
_PHONE_RE = re.compile(
    r"(?<!\w)"
    r"(?:(?:\+33|0033)(?:\s?\(0\))?\s?0?|0)"   # préfixe : +33 / 0033 / 0
    r"[1-9]"                                     # premier chiffre significatif
    r"(?:[\s.-]?\d{2}){4}"                       # 4 groupes de 2 chiffres
    r"(?!\w)"
)

# Code postal français (départements 01-98), suivi d'une ville optionnelle
# (1 à 4 mots capitalisés). Seul le code postal est aussi remplacé. Le reste
# de la ligne (dates, téléphone, ``|``…) n'est plus avalé : la ville s'arrête
# au premier mot qui ne ressemble pas à un mot de ville.
_POSTAL_CITY_RE = re.compile(
    r"(?<!\d)(?:0[1-9]|[1-8]\d|9[0-8])\d{3}(?!\d)"
    r"(?:[ \t\-–—]*[A-Za-zÀ-ÿ']+(?:[ -][A-Za-zÀ-ÿ']+){0,3})?"
)


def anonymize_cv(text: str, name: str = "") -> str:
    """Retire les données personnelles d'un CV avant envoi au LLM.

    Args:
        text: contenu brut du CV (``cv_raw_json.raw_content``).
        name: nom complet du candidat (``headline`` du profil), dont chaque
            mot est retiré du texte s'il y figure. S'il ne ressemble pas à un
            nom de personne (ex. un intitulé de poste), il est ignoré et la
            détection automatique depuis le CV est utilisée.

    Returns:
        Le texte anonymisé (placeholders ``[NOM]``, ``[EMAIL]``…).
    """
    if not text:
        return text

    text = _EMAIL_RE.sub(_EMAIL, text)
    text = _LINKEDIN_RE.sub(_LINKEDIN, text)
    text = _PHONE_RE.sub(_PHONE, text)
    text = _POSTAL_CITY_RE.sub(_POSTAL_CITY, text)

    # Nom fourni par le profil ; sinon détection automatique depuis le CV. Le
    # nom est validé (``_leading_name``) : un intitulé de poste passé en
    # ``name`` (ex. ``profile.headline`` = titre en gras du CV) ferait
    # confiance à un non-nom et sauterait la détection automatique — le vrai
    # nom du candidat resterait en clair dans le texte envoyé au LLM (fuite
    # PII, constat de revue). Sans ``_extract_name``, un CV dont le nom est une
    # première ligne simple (ni ``#`` ni ``**``) laisserait aussi fuir le nom.
    if name:
        name = _leading_name(name)
    if not name:
        name = _extract_name(text)
    if name:
        text = _anonymize_name(text, name)
    return text


# --- Anonymisation du nom ---------------------------------------------------

# Mots courants (français, intitulés de poste, mots techniques) qui ne sont
# jamais des tokens de nom : ne pas les remplacer par ``[NOM]`` — un prénom ou
# un nom très fréquent (ex. ``Data``) mutilerait le contenu du CV.
_COMMON_WORDS = {
    # Mots outils français.
    "de", "du", "des", "le", "la", "les", "un", "une", "et", "ou", "en",
    "au", "aux", "à", "a", "sur", "sous", "dans", "par", "pour", "avec",
    "sans", "son", "sa", "ses", "mon", "ma", "mes", "ton", "ta", "tes",
    "se", "ce", "ces", "il", "elle", "je", "tu", "nous", "vous", "ils",
    "ne", "pas", "plus", "très", "bien", "aussi",
    # Mots très courants de CV / intitulés de poste.
    "cv", "resume", "curriculum", "data", "engineer", "engineering",
    "senior", "junior", "développeur", "developpeur", "développeuse",
    "developpeuse", "ingénieur", "ingenieur", "technicien", "architecte",
    "fullstack", "full-stack", "stack", "software", "developer", "analyst",
    "consultant", "manager", "responsable", "directeur", "chargé", "charge",
}

# Ligne de titre « simple » ressemblant à un nom : 1 à 3 mots capitalisés
# (ex. ``Jean Dupont``, ``Jean-Marc Dupont``, ``NOUANE Victor``), sans
# ponctuation. Une lettre majuscule peut être suivie de majuscules (un nom en
# petites capitales, ex. ``NOUANE``) ou d'une apostrophe (ex. ``D'Argent``).
_PLAIN_NAME_RE = re.compile(
    r"^[A-ZÀ-Ý][A-Za-zÀ-ÿ']*(?:[ -][A-ZÀ-Ý][A-Za-zÀ-ÿ']*){0,2}$"
)


def looks_like_name(line: str) -> bool:
    """Une ligne simple ressemble-t-elle à un nom de personne (et pas à un titre) ?

    Utilisé par ``_extract_name`` (anonymisation) et par ``profile_parser``
    (headline du profil) : le nom d'un CV n'est pas toujours un heading ``#``
    ni un texte en gras, mais souvent une simple première ligne.
    """
    if not _PLAIN_NAME_RE.match(line):
        return False
    if _is_section_title(line):
        return False
    return not any(
        token.lower().rstrip(".,;") in _COMMON_WORDS for token in line.split()
    )


def _leading_name(title: str) -> str:
    """Préfixe de ``title`` ressemblant à un nom de personne (1 à 3 mots
    capitalisés), ou ``""`` si la ligne ne débute pas par un nom.

    Une ligne de titre combine souvent nom et intitulé de poste (ex. ``Jean
    Dupont — Data Engineer``) : seul le préfixe nominal est retenu. Un
    intitulé seul (ex. ``Data Engineer — Acme``) ne commence par aucun nom —
    ``Data``/``Engineer`` sont des mots courants de CV (``_COMMON_WORDS``) —
    et renvoie ``""`` : le traiter comme le nom du candidat désactiverait la
    détection du vrai nom et laisserait fuir les données personnelles au LLM
    (constat de revue).
    """
    m = re.match(
        r"^[A-ZÀ-Ý][A-Za-zÀ-ÿ']*(?:[ -][A-ZÀ-Ý][A-Za-zÀ-ÿ']*){0,2}", title or ""
    )
    if not m:
        return ""
    candidate = m.group(0)
    return candidate if looks_like_name(candidate) else ""


def _anonymize_name(text: str, name: str) -> str:
    """Retire le nom du candidat d'un texte anonymisé.

    Le nom complet est d'abord remplacé (le bloc ``Prénom Nom`` devient
    ``[NOM]``), puis chaque mot d'au moins 3 lettres hors ``_COMMON_WORDS`` est
    remplacé individuellement. Sans la garde de mots courants, un token très
    fréquent (ex. ``data``, ``senior``) dégraderait le contenu du CV.
    """
    name_clean = re.sub(r"\s+", " ", name.strip())
    if not name_clean:
        return text
    text = re.sub(
        rf"\b{re.escape(name_clean)}\b", _NAME, text, flags=re.IGNORECASE
    )
    for token in (t for t in name_clean.split() if t):
        if len(token) < 3 or token.lower() in _COMMON_WORDS:
            continue
        text = re.sub(
            rf"\b{re.escape(token)}\b", _NAME, text, flags=re.IGNORECASE
        )
    return text


# --- Extraction et réinjection des coordonnées (génération de CV) ----------

# Aliases de rubriques du CV (mêmes valeurs que profile_parser._SECTION_ALIASES,
# dupliquées ici pour ne pas créer de dépendance core→services).
_SECTION_TITLE_HINTS = (
    "résumé", "resume", "profil", "summary", "à propos", "a propos",
    "compétences", "competences", "skills", "technologies", "expertise",
    "expérience", "experience", "parcours professionnel",
    "formation", "education", "diplômes", "diplomes",
    "projets", "projet", "projects", "project",
)


def _is_section_title(title: str) -> bool:
    """Une ligne de titre est-elle une rubrique de CV (à ne pas traiter comme un nom) ?"""
    normalized = re.sub(r"[^a-zà-ÿ0-9\s]", "", title.strip().lower())
    return any(hint in normalized for hint in _SECTION_TITLE_HINTS)


def _extract_name(text: str) -> str:
    """Première ligne de titre du CV (``# Nom``, ``**Nom**`` ou ligne simple).

    Même logique que ``profile_parser._extract_headline``, réimplémentée ici
    pour rester dans ``core`` (pas de dépendance vers ``services``). Seul un
    nom de personne est retenu (``_leading_name`` / ``looks_like_name``) : un
    intitulé de poste en titre n'est pas le nom du candidat et ne doit pas
    désactiver la détection. En dernier recours, une ligne simple ressemblant
    à un nom (``Jean Dupont``) est capturée — sans quoi un CV dont le nom
    n'est pas un titre laisserait fuir le vrai nom vers le LLM.
    """
    plain_candidate = ""
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title and not _is_section_title(title):
                name = _leading_name(title)
                if name:
                    return name
        else:
            match = re.match(r"^\*\*(.+?)\*\*\s*$", stripped)
            if match:
                name = _leading_name(match.group(1))
                if name:
                    return name
            if not plain_candidate and looks_like_name(stripped):
                plain_candidate = stripped
    return plain_candidate


def extract_contact_info(text: str) -> dict:
    """Capture les coordonnées réelles d'un CV (avant anonymisation).

    Retourne ``{name, email, phone, linkedin, location}`` — chaque valeur est
    ``""`` si absente. Réutilise les regex d'anonymisation en mode ``findall``.
    """
    text = text or ""
    emails = _EMAIL_RE.findall(text)
    phones = _PHONE_RE.findall(text)
    linkedins = _LINKEDIN_RE.findall(text)
    locations = _POSTAL_CITY_RE.findall(text)
    return {
        "name": _extract_name(text),
        "email": emails[0] if emails else "",
        "phone": phones[0] if phones else "",
        "linkedin": linkedins[0] if linkedins else "",
        "location": locations[0].strip() if locations else "",
    }


_PLACEHOLDER_TO_KEY = {
    _NAME: "name",
    _EMAIL: "email",
    _PHONE: "phone",
    _LINKEDIN: "linkedin",
    _POSTAL_CITY: "location",
}

# Placeholders d'une ligne de coordonnées (l'en-tête serveur la réinjecte).
_CONTACT_PLACEHOLDERS = {_EMAIL, _PHONE, _LINKEDIN, _POSTAL_CITY}


def _heading_text(line: str) -> str | None:
    """Texte d'une ligne de titre (``# Titre`` ou ``**Titre**``), sinon ``None``."""
    stripped = line.strip()
    if stripped.startswith("#"):
        title = stripped.lstrip("#").strip()
        return title or None
    match = re.match(r"^\*\*(.+?)\*\*\s*$", stripped)
    if match:
        return match.group(1).strip()
    return None


def _is_identity_heading(heading: str, name: str) -> bool:
    """L'en-tête ne porte-t-il que l'identité du candidat ?

    Placeholder de nom (``[NOM]``, éventuellement répété — ``[NOM] [NOM]``
    quand l'anonymisation remplace chaque mot du nom) ou nom réel capturé.
    """
    if heading in _PLACEHOLDER_TO_KEY:
        return True
    if name and name.lower() in heading.lower():
        return True
    tokens = heading.split()
    return bool(tokens) and all(t == _NAME for t in tokens)


# Placeholders autorisés dans une ligne de contact reproduite par le LLM :
# coordonnées (``_CONTACT_PLACEHOLDERS``) + nom (``[NOM]`` — le LLM peut le
# préfixer sur la même ligne).
_CONTACT_LINE_TOKENS = _CONTACT_PLACEHOLDERS | {_NAME}


def _is_contact_line(line: str) -> bool:
    """Une ligne ne contient-elle que des placeholders de contact ?

    Ex. ``[EMAIL] | [TÉLÉPHONE] | [VILLE] | [LINKEDIN]`` (ou ``[NOM] | [EMAIL]``)
    — la ligne de coordonnées que le LLM reproduit depuis le CV anonymisé,
    retirée car ``inject_contact_info`` réinjecte les coordonnées réelles
    (après le titre de poste) côté serveur.

    La ligne doit porter **au moins un placeholder de contact** (sinon une
    rangée de tableau ``|---|---|`` serait retirée à tort) et, une fois les
    placeholders retirés, ne plus contenir aucun caractère réel — la syntaxe
    Markdown résiduelle (parenthèses d'un lien ``[LINKEDIN]([LINKEDIN])`` →
    ``()``, ``|``, ``*``, tirets, espaces…) est tolérée, tout contenu réel
    (lettre, chiffre, accent) la fait échouer.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if not any(p in stripped for p in _CONTACT_LINE_TOKENS):
        return False
    remainder = stripped
    for placeholder in _CONTACT_LINE_TOKENS:
        remainder = remainder.replace(placeholder, "")
    # Seule de la ponctuation de séparation peut rester — aucun caractère réel.
    return not re.search(r"[A-Za-zÀ-ÿ0-9]", remainder)


def _strip_leading_identity(lines: list, name: str) -> list:
    """Retire le bloc d'identité (nom + coordonnées) écrit par le LLM.

    Parcourt les lignes d'en-tête et retire la ligne de nom (``# Nom`` ou
    ``**Nom**``) et les lignes de coordonnées (placeholders ``[EMAIL]``,
    ``[TÉLÉPHONE]``…), dans n'importe quel ordre, séparées par d'éventuels
    retours à la ligne. Une rubrique légitime (``# Résumé``) n'est jamais
    touchée.
    """
    if not lines:
        return lines

    i = 0
    stripped = False
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        heading = _heading_text(line)
        if heading is not None and _is_identity_heading(heading, name):
            i += 1
            stripped = True
            continue
        if _is_contact_line(line):
            i += 1
            stripped = True
            continue
        break
    return lines[i:] if stripped else lines


def _build_contact_line(contact: dict) -> str:
    """Ligne de coordonnées réelles (``ville | téléphone | email | linkedin``)."""
    return " | ".join(
        value
        for value in (
            contact.get("location"),
            contact.get("phone"),
            contact.get("email"),
            contact.get("linkedin"),
        )
        if value
    )


def _build_header(contact: dict) -> str:
    """En-tête Markdown construit par le serveur (nom + coordonnées trouvées).

    Utilisé quand le CV généré n'a pas de titre de poste (le corps commence
    directement par une rubrique ``##``) : nom et coordonnées restent regroupés
    en tête, comme historiquement. Quand un titre existe, ``inject_contact_info``
    place la ligne de coordonnées après le titre et n'utilise ici que le nom.
    """
    lines = []
    if contact.get("name"):
        lines.append(f"# {contact['name']}")
    contact_line = _build_contact_line(contact)
    if contact_line:
        lines.append(contact_line)
    return "\n".join(lines)


def _split_title(body: str) -> tuple[str | None, str]:
    """Sépare la première ligne de contenu (titre de poste) du reste du corps.

    Le titre est la première ligne non vide qui n'est ni une rubrique (``#``),
    ni un séparateur (``---``) — ex. ``**Data Engineer - Agentic AI…**``.
    Sans titre, retourne ``(None, body)``.
    """
    lines = (body or "").splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return None, body
        if re.match(r"^[-*_]{3,}\s*$", stripped):
            return None, body
        return line, "\n".join(lines[i + 1:]).strip()
    return None, body


def inject_contact_info(markdown: str, contact: dict) -> str:
    """Réinjecte les coordonnées réelles dans un CV généré (en-tête serveur).

    Retire d'abord les lignes de coordonnées (placeholders) que le LLM a
    reproduites depuis le CV anonymisé — **où qu'elles soient**, pas seulement
    en tête — puis remplace les placeholders restants par les valeurs capturées
    (un placeholder sans valeur est retiré, jamais laissé visible). Le nom est
    préfixé en ``# NOM`` et la ligne de coordonnées est insérée **juste après
    le titre de poste** (première ligne de contenu du CV, ex. ``**Data
    Engineer - Agentic AI…**``) — pas après le nom. Sans titre (corps commençant
    par une rubrique), nom et coordonnées restent regroupés en en-tête. Sans ce
    retrait global, la ligne de contact apparaîtrait deux fois dans le CV
    (en-tête serveur + ligne reproduite, dont les placeholders seraient
    remplacés par les vraies coordonnées).
    """
    lines = [
        line
        for line in (markdown or "").splitlines()
        if not _is_contact_line(line)
    ]
    lines = _strip_leading_identity(lines, contact.get("name") or "")
    # Réduit les lignes vides laissées par le retrait d'une ligne au milieu.
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    for placeholder, key in _PLACEHOLDER_TO_KEY.items():
        value = (contact.get(key) or "").strip()
        body = body.replace(placeholder, value if value else "")
    body = body.strip()

    name = (contact.get("name") or "").strip()
    name_header = f"# {name}" if name else ""
    contact_line = _build_contact_line(contact)

    title, rest = _split_title(body)
    if title is not None:
        # Titre de poste présent : la ligne de coordonnées s'insère juste après
        # le titre (sans ligne vide), le nom restant au-dessus.
        block = title
        if contact_line:
            # Retour à la ligne dur Markdown si le titre n'en porte pas déjà un.
            if not re.search(r"(\\| {2})$", title):
                title = f"{title}  "
            block = f"{title}\n{contact_line}"
        if rest:
            block = f"{block}\n\n{rest}"
        return f"{name_header}\n\n{block}".strip() if name_header else block.strip()

    # Pas de titre de poste : comportement historique (nom + coordonnées en tête).
    header = _build_header(contact)
    if not header:
        return body
    return f"{header}\n\n{body}".strip()


def _replace_contact_placeholders(text: str) -> str:
    """Retire les placeholders de coordonnées d'un texte (remplacés par ``""``)."""
    for placeholder in _PLACEHOLDER_TO_KEY:
        text = text.replace(placeholder, "")
    return text


def clean_letter_markdown(markdown: str, name: str = "") -> str:
    """Nettoie une lettre de motivation générée par le LLM.

    Retire un éventuel bloc d'identité (en-tête ``# [NOM]``…) que le LLM aurait
    écrit, puis les placeholders de coordonnées résiduels (``[NOM]``, ``[EMAIL]``,
    ``[TÉLÉPHONE]``, ``[VILLE]``, ``[LINKEDIN]``). **Aucune coordonnée réelle
    n'est réinjectée** : la lettre est anonyme et se termine par la formule de
    politesse du LLM. Les lignes vides (séparation des paragraphes) sont
    conservées.
    """
    lines = _strip_leading_identity((markdown or "").splitlines(), name)
    out = []
    for line in lines:
        # Ligne de coordonnées écrite par le LLM (placeholders séparés par ``|``,
        # ex. ``[EMAIL] | [TÉLÉPHONE] | [VILLE] | [LINKEDIN]``) : retirée.
        segments = [seg.strip() for seg in line.split("|")]
        if any(any(p in seg for p in _CONTACT_PLACEHOLDERS) for seg in segments):
            continue
        # Ligne de nom écrite par le LLM : ``[NOM]``, répété quand l'anonymisation
        # a remplacé chaque mot du nom (``[NOM] [NOM]``), éventuellement en gras.
        name_tokens = line.replace("*", "").split()
        if name_tokens and all(t == _NAME for t in name_tokens):
            continue
        # Ligne ordinaire : les placeholders restants sont retirés ; une ligne
        # non vide devenue vide (placeholder sans valeur) est retirée, une ligne
        # vide de séparation est conservée.
        cleaned = _replace_contact_placeholders(line)
        if cleaned.strip() or not line.strip():
            out.append(cleaned)
    return "\n".join(out).strip()
