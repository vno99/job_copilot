"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import type { JobOfferListItem, SortField } from "@/lib/api";
import { formatLocation } from "@/lib/location";
import {
  ApplicationSubmittedIcon,
  Button,
  Card,
  CvGeneratedIcon,
  LetterGeneratedIcon,
  ScorePill,
} from "@/components/ui";

// Case « tout sélectionner » de la page courante, avec état indéterminé quand
// seule une partie des lignes est cochée.
function IndeterminateCheckbox({
  checked,
  indeterminate,
  onChange,
}: {
  checked: boolean;
  indeterminate: boolean;
  onChange: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      onChange={onChange}
      className="h-4 w-4 rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900"
    />
  );
}

// En-tête triable : un clic trie par cette colonne, un second clic inverse le sens.
// La colonne active ressort : fond teinté + texte accentué + flèche dans un badge.
function SortHeader({
  label,
  field,
  sort,
  onSort,
}: {
  label: string;
  field: SortField;
  sort: { field: SortField; order: "asc" | "desc" };
  onSort: (field: SortField) => void;
}) {
  const active = sort.field === field;
  return (
    <th
      aria-sort={
        active ? (sort.order === "asc" ? "ascending" : "descending") : "none"
      }
      className={`px-4 py-2 ${active ? "bg-sky-50" : ""}`}
    >
      <button
        type="button"
        onClick={() => onSort(field)}
        className={`inline-flex items-center gap-1.5 font-medium tracking-wide transition-colors ${
          active
            ? "font-semibold text-sky-800"
            : "text-zinc-500 hover:text-zinc-700"
        }`}
      >
        {label}
        <span
          aria-hidden
          className={`inline-flex h-4 w-4 items-center justify-center rounded text-[10px] leading-none ${
            active ? "bg-sky-100 text-sky-800" : "text-zinc-400"
          }`}
        >
          {active ? (sort.order === "asc" ? "↑" : "↓") : "↕"}
        </span>
      </button>
    </th>
  );
}

interface OffersTableProps {
  items: JobOfferListItem[];
  total: number;
  limit: number;
  offset: number;
  // Titre du tableau (rendu en <caption> sr-only) — exposé aux lecteurs
  // d'écran sans modifier la mise en page.
  caption?: string;
  sort: { field: SortField; order: "asc" | "desc" };
  onSort: (field: SortField) => void;
  onOffsetChange: (offset: number) => void;
  // Cible du clic ligne / « Voir » : lien vers le détail (profil le mieux
  // noté par défaut). Le composant construit lui-même les liens des pills de
  // score et de l'icône « + » (détail sur le profil actif).
  detailHref: (item: JobOfferListItem) => string;
  // Profil par défaut pour l'icône « + » (voir tous les scores) ; absent →
  // le détail s'ouvre sans profil ciblé (l'API utilise le profil actif).
  defaultProfileId?: number | null;
  // Sélection en masse (archiver / désarchiver) : colonne de cases à gauche.
  selectable?: boolean;
  selectedIds?: number[];
  onToggleSelect?: (id: number) => void;
  onToggleSelectPage?: (pageIds: number[], select: boolean) => void;
}

export function OffersTable({
  items,
  total,
  limit,
  offset,
  caption,
  sort,
  onSort,
  onOffsetChange,
  detailHref,
  defaultProfileId = null,
  selectable = false,
  selectedIds = [],
  onToggleSelect = () => {},
  onToggleSelectPage = () => {},
}: OffersTableProps) {
  const router = useRouter();
  const toggleSort = (field: SortField) => {
    onOffsetChange(0); // le tri repart de la première page
    onSort(field);
  };

  // Fond des cellules : la colonne triée ressort sur toute sa hauteur
  // (fond teinté, qui s'intensifie au survol de la ligne via le groupe).
  const sortedColBg = (field: SortField) =>
    sort.field === field ? "bg-sky-50/60 group-hover:bg-sky-100" : "";

  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));

  // Sélection « tout » / « partiel » sur la page courante.
  const pageIds = items.map((o) => o.id);
  const allPageSelected =
    pageIds.length > 0 && pageIds.every((id) => selectedIds.includes(id));
  const somePageSelected = pageIds.some((id) => selectedIds.includes(id));

  return (
    <>
      <Card className="mt-4 overflow-hidden">
        <table className="w-full text-sm">
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead className="bg-zinc-50 text-left text-xs uppercase text-zinc-500">
            <tr>
              {selectable && (
                <th className="w-10 px-4 py-2">
                  <IndeterminateCheckbox
                    checked={allPageSelected}
                    indeterminate={somePageSelected && !allPageSelected}
                    onChange={() => onToggleSelectPage(pageIds, !allPageSelected)}
                  />
                </th>
              )}
              <SortHeader label="Titre" field="title" sort={sort} onSort={toggleSort} />
              <SortHeader label="Date de création" field="ingested_at" sort={sort} onSort={toggleSort} />
              <SortHeader label="Entreprise" field="company" sort={sort} onSort={toggleSort} />
              <SortHeader label="Localisation" field="location" sort={sort} onSort={toggleSort} />
              <th className="px-4 py-2 font-medium">Contrat</th>
              <SortHeader label="Source" field="source" sort={sort} onSort={toggleSort} />
              <th className="px-4 py-2 font-medium">Score</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {items.map((o) => (
              <tr
                key={o.id}
                className="group cursor-pointer hover:bg-zinc-50"
                onClick={() => router.push(detailHref(o))}
              >
                {selectable && (
                  <td
                    className="cursor-default px-4 py-2"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(o.id)}
                      onChange={() => onToggleSelect(o.id)}
                      aria-label={`Sélectionner ${o.title ?? `Offre ${o.id}`}`}
                      className="h-4 w-4 rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900"
                    />
                  </td>
                )}
                <td
                  className={`px-4 py-2 font-medium text-zinc-900 ${sortedColBg("title")}`}
                >
                  {o.title ?? "Sans titre"}
                </td>
                <td
                  className={`whitespace-nowrap px-4 py-2 text-zinc-600 ${sortedColBg("ingested_at")}`}
                >
                  {new Date(o.ingested_at).toLocaleDateString("fr-FR", {
                    day: "2-digit",
                    month: "2-digit",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </td>
                <td className={`px-4 py-2 text-zinc-600 ${sortedColBg("company")}`}>
                  {o.company ?? "—"}
                </td>
                <td className={`px-4 py-2 text-zinc-600 ${sortedColBg("location")}`}>
                  {formatLocation(o.location)}
                </td>
                <td className="px-4 py-2 text-zinc-600">
                  {o.contract_type ?? "—"}
                </td>
                <td className={`px-4 py-2 text-zinc-600 ${sortedColBg("source")}`}>
                  {o.source ?? "—"}
                </td>
                <td className="px-4 py-2">
                  {o.scores.length === 0 ? (
                    <span className="text-zinc-400">—</span>
                  ) : (
                    <div className="flex flex-wrap gap-3">
                      {o.scores.slice(0, 5).map((s) => (
                        // Unité « score » : la pill reste le seul élément
                        // cliquable ; les icônes (CV, lettre) sont des
                        // indicateurs non cliquables.
                        <span
                          key={s.candidate_profile_id}
                          className="inline-flex items-center gap-0.5"
                        >
                          <Link
                            href={`/offers/${o.id}?candidate_profile_id=${s.candidate_profile_id}`}
                            onClick={(e) => e.stopPropagation()}
                            title={s.profile_name ?? "Profil"}
                          >
                            <ScorePill score={s.total_score} />
                          </Link>
                          {s.has_cv && <CvGeneratedIcon />}
                          {s.has_letter && <LetterGeneratedIcon />}
                          {s.application_submitted && (
                            <ApplicationSubmittedIcon />
                          )}
                        </span>
                      ))}
                      {o.scores.length > 5 && (
                        <Link
                          href={
                            defaultProfileId != null
                              ? `/offers/${o.id}?candidate_profile_id=${defaultProfileId}`
                              : `/offers/${o.id}`
                          }
                          onClick={(e) => e.stopPropagation()}
                          title="Voir tous les scores"
                          className="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold text-zinc-600 transition-colors hover:bg-zinc-200"
                        >
                          +
                        </Link>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {/* Pagination */}
      {pages > 1 && (
        <div className="mt-4 flex items-center justify-between text-sm">
          <Button
            variant="secondary"
            disabled={offset === 0}
            onClick={() => onOffsetChange(Math.max(0, offset - limit))}
          >
            ← Précédent
          </Button>
          <span className="text-zinc-500">
            Page {page} / {pages}
          </span>
          <Button
            variant="secondary"
            disabled={offset + limit >= total}
            onClick={() => onOffsetChange(offset + limit)}
          >
            Suivant →
          </Button>
        </div>
      )}
    </>
  );
}
