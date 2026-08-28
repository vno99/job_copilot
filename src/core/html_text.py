"""Conversion HTML → texte préservant la structure (paragraphes, listes).

``" ".join(element.itertext())`` concatène tous les nœuds texte d'un élément
avec un simple espace : les frontières de paragraphes et d'items de liste sont
perdues, et une offre dont la page affiche missions et avantages en blocs
arrive en base comme un seul paragraphe compact (description « horrible »).

``element_to_text`` insère un retour à la ligne aux frontières des éléments de
bloc (``<p>``, ``<li>``, ``<div>``, titres…), préfixe chaque item de liste par
``- `` et convertit les ``<br>`` en retour à la ligne : la structure de la page
survit à la conversion en texte — c'est ce que voit le LLM d'extraction d'offre
(``url_offer_extractor``), qui doit pouvoir la retranscrire dans sa description.
"""

import re

# Éléments de bloc : un retour à la ligne est inséré autour de leur contenu.
_BLOCK_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "dd", "details", "div", "dl",
    "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
    "h3", "h4", "h5", "h6", "header", "li", "main", "nav", "ol", "p", "pre",
    "section", "summary", "table", "tbody", "td", "tfoot", "th", "thead",
    "tr", "ul",
})

_IGNORED_TAGS = frozenset({"script", "style", "noscript", "svg"})


def element_to_text(root) -> str:
    """Texte de ``root``, retours à la ligne aux frontières de blocs.

    Le contenu inline (``<p>a <b>b</b> c</p>``) reste sur une même ligne ; chaque
    bloc (paragraphe, item de liste, titre) est séparé du suivant par un retour
    à la ligne, chaque item de liste (au contenu direct) est préfixé par ``- ``,
    les ``<br>`` sont convertis en retour à la ligne. ``<script>``/
    ``<style>``/``<noscript>``/``<svg>`` sont ignorés. Les espaces multiples et
    les lignes vides en trop sont réduits.

    Args:
        root: élément lxml (ou racine ``etree.HTML``) à convertir.

    Returns:
        Le texte, avec un retour à la ligne par bloc affiché.
    """
    parts: list[str] = []
    for element in root.iter():
        tag = element.tag if isinstance(element.tag, str) else None
        if tag is None or tag in _IGNORED_TAGS:
            continue
        if tag == "br":
            parts.append("\n")
        elif tag == "li" and element.text and element.text.strip():
            # Item de liste au contenu direct : le préfixe « - » rend la liste
            # visible au LLM (le caractère puce est dessiné par le CSS, absent
            # du texte). Un <li> imbriquant des blocs (contenu indirect) est
            # simplement traité comme un bloc.
            parts.append("\n- ")
        elif tag in _BLOCK_TAGS:
            parts.append("\n")
        if element.text:
            parts.append(element.text)
        if element.tail:
            parts.append(element.tail)
    text = "".join(parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()
