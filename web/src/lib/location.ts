/**
 * Formate la localisation d'une offre pour l'affichage « N° département - Ville ».
 *
 * Les localisations Hellowork sont typiquement « Ville - 92 » (ville d'abord,
 * département ensuite) : on inverse pour afficher « 92 - Ville ». Les formats
 * sans département (ex. « Paris ») ou déjà « département - ville » (ex.
 * « 92 - Hauts-de-Seine ») sont renvoyés tels quels. Un code postal en tête
 * (ex. « 75011 Paris ») est réduit à son département (« 75 - Paris »).
 */
export function formatLocation(location: string | null): string {
  if (!location) return "—";
  const trimmed = location.trim();

  // « Ville - 92 » → « 92 - Ville » (tirets entourés d'espaces uniquement,
  // pour ne pas casser « Aix-en-Provence »)
  const parts = trimmed.split(/\s+-\s+/).map((p) => p.trim()).filter(Boolean);
  if (parts.length === 2 && /^\d{2,3}$/.test(parts[1])) {
    return `${parts[1]} - ${parts[0]}`;
  }

  // « 75011 Paris » → « 75 - Paris »
  const postal = trimmed.match(/^(\d{5})\s+(.+)$/);
  if (postal) {
    return `${postal[1].slice(0, 2)} - ${postal[2]}`;
  }

  return trimmed;
}
