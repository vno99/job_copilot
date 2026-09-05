"use client";

import { Card } from "@/components/ui";
import type { SearchParameter } from "@/lib/api";

// Tableau des recherches sauvegardées (Lancer, Titre, Source, URL, Max offres,
// Statut). Un clic sur une ligne déclenche l'édition ; les boutons (lancement,
// toggle d'activation, suppression) interrompent la propagation pour ne pas
// ouvrir l'édition.
export function SearchSettingsTable({
  items,
  onEdit,
  onDelete,
  onToggleActive,
  onRun,
  disabled = false,
  runDisabled = false,
  runningId = null,
}: {
  items: SearchParameter[];
  onEdit: (parameter: SearchParameter) => void;
  onDelete: (parameter: SearchParameter) => void;
  onToggleActive: (parameter: SearchParameter) => void;
  onRun: (parameter: SearchParameter) => void;
  disabled?: boolean;
  runDisabled?: boolean;
  runningId?: number | null;
}) {
  return (
    <Card className="mt-4 overflow-hidden">
      <table className="w-full text-sm">
        <caption className="sr-only">Recherches sauvegardées</caption>
        <thead className="bg-zinc-50 text-left text-xs uppercase text-zinc-500">
          <tr>
            {/* Colonne « Lancer » : triangle vert (lecture) déclenchant le
                lancement unitaire de la recherche de la ligne. */}
            <th className="w-10 px-4 py-2">
              <span className="sr-only">Lancer</span>
            </th>
            <th className="px-4 py-2 font-medium">Titre</th>
            <th className="px-4 py-2 font-medium">Source</th>
            <th className="px-4 py-2 font-medium">URL</th>
            <th className="px-4 py-2 font-medium">Max offres</th>
            <th className="px-4 py-2 font-medium">Statut</th>
            <th className="w-10 px-4 py-2" />
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100">
          {items.map((p) => (
            <tr
              key={p.id}
              className="group cursor-pointer hover:bg-zinc-50"
              onClick={() => onEdit(p)}
            >
              <td
                className="px-4 py-2"
                onClick={(e) => e.stopPropagation()}
              >
                {/* Lancement unitaire : une seule ligne à la fois (global et
                    unitaire), le triangle passe en spinner pendant le run. */}
                <button
                  type="button"
                  onClick={() => onRun(p)}
                  disabled={runDisabled}
                  aria-label={`Lancer la recherche « ${p.title} »`}
                  title={
                    p.is_active
                      ? "Lancer cette recherche maintenant"
                      : "Lancer cette recherche maintenant (même si inactive)"
                  }
                  className="rounded-md p-1.5 text-emerald-600 transition-colors hover:bg-emerald-50 hover:text-emerald-700 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {runningId === p.id ? (
                    <span
                      aria-hidden="true"
                      className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-emerald-600 border-t-transparent"
                    />
                  ) : (
                    <svg
                      viewBox="0 0 16 16"
                      fill="currentColor"
                      className="h-4 w-4"
                      aria-hidden="true"
                    >
                      <path d="M5.5 3.5l7 4.5-7 4.5z" />
                    </svg>
                  )}
                </button>
              </td>
              <td className="px-4 py-2 font-medium text-zinc-900">{p.title}</td>
              <td className="whitespace-nowrap px-4 py-2 text-zinc-600">
                {p.source}
              </td>
              {/* URL cliquable (nouvel onglet) : le tooltip natif expose l'URL
                  complète ; stopPropagation empêche le clic d'ouvrir l'édition. */}
              <td
                className="max-w-0 px-4 py-2"
                onClick={(e) => e.stopPropagation()}
              >
                <a
                  href={p.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={p.url}
                  className="block truncate text-blue-600 hover:underline"
                >
                  {p.url}
                </a>
              </td>
              <td className="px-4 py-2 text-zinc-600">{p.max_offers}</td>
              <td className="px-4 py-2">
                {/* Bascule d'activation dans la colonne Statut : cercle vert à
                    coche (actif) / cercle rouge « sens interdit » (inactif). Le
                    clic n'ouvre pas l'édition de la ligne. */}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleActive(p);
                  }}
                  disabled={disabled}
                  aria-label={
                    p.is_active
                      ? `Désactiver ${p.title}`
                      : `Activer ${p.title}`
                  }
                  title={
                    p.is_active
                      ? "Désactiver (ignoré par l'agent de recherche)"
                      : "Activer (pris en compte par l'agent de recherche)"
                  }
                  className={`inline-flex items-center gap-1.5 rounded-md px-1 py-0.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                    p.is_active
                      ? "text-emerald-700 hover:bg-emerald-50"
                      : "text-red-700 hover:bg-red-50"
                  }`}
                >
                  {p.is_active ? (
                    <svg
                      viewBox="0 0 16 16"
                      className="h-4 w-4 text-emerald-600"
                      aria-hidden="true"
                    >
                      <circle cx="8" cy="8" r="7" fill="currentColor" />
                      <path
                        d="M5 8l2 2 4-4"
                        fill="none"
                        stroke="#fff"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  ) : (
                    <svg
                      viewBox="0 0 16 16"
                      className="h-4 w-4 text-red-600"
                      aria-hidden="true"
                    >
                      <circle cx="8" cy="8" r="7" fill="currentColor" />
                      <path
                        d="M5 8h6"
                        fill="none"
                        stroke="#fff"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                      />
                    </svg>
                  )}
                  {p.is_active ? "Actif" : "Inactif"}
                </button>
              </td>
              <td
                className="px-4 py-2 text-right"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  onClick={() => onDelete(p)}
                  aria-label={`Supprimer ${p.title}`}
                  className="rounded-md p-1 text-zinc-400 transition-colors hover:bg-red-50 hover:text-red-600"
                >
                  <svg
                    viewBox="0 0 16 16"
                    className="h-4 w-4"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M3 4h10M6 4V2.5h4V4M5 4l.5 9h5l.5-9M6.5 7v3M9.5 7v3" />
                  </svg>
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
