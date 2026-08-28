/**
 * Formate une date/heure ISO pour l'affichage « JJ/MM/AAAA à HH:MM » (locale
 * fr-FR). Utilisé pour les horodatages du détail d'offre : date du matching,
 * date de génération du CV et de la lettre de motivation.
 */
export function formatDateTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const date = d.toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
  const time = d.toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${date} à ${time}`;
}

/**
 * Formate une date seule « YYYY-MM-DD » (ex. `published_date` d'une offre) pour
 * l'affichage « JJ/MM/AAAA ». Parsée par composants : `new Date("YYYY-MM-DD")`
 * interprète minuit UTC et peut décaler d'un jour dans les fuseaux négatifs.
 * Retourne "" si absente ou illisible.
 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return "";
  const [, y, mo, d] = m;
  return `${d}/${mo}/${y}`;
}
