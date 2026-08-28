"use client";

import { useState } from "react";
import type { QueryClient } from "@tanstack/react-query";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AddOffersResult, SortField } from "@/lib/api";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { Button, EmptyState, ErrorBox, Spinner } from "@/components/ui";
import { AddOfferModal } from "@/components/add-offer-modal";
import { OffersTable } from "@/components/offers-table";

const PAGE_SIZE = 25;

// Navigateur d'offres partagé par les pages « Offres » (actives) et « Offres
// archivées » : même tableau, filtre, tri et pagination. Seules la cible de
// l'action en masse et les libellés diffèrent selon `archived`.
export function OffersBrowser({ archived }: { archived: boolean }) {
  const qc = useQueryClient();
  const [company, setCompany] = useState("");
  const [source, setSource] = useState("");
  const [offset, setOffset] = useState(0);
  // Sélection en masse pour l'archivage / désarchivage (par id d'offre).
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  // Modale « Ajouter des offres d'emploi » (ajout manuel par URL).
  const [showAddModal, setShowAddModal] = useState(false);
  // Résultat de l'ingestion (affiché dans la modale, qui reste ouverte).
  const [addResult, setAddResult] = useState<AddOffersResult | null>(null);
  const toggleSelect = (id: number) =>
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  const toggleSelectPage = (pageIds: number[], select: boolean) =>
    setSelectedIds((prev) => {
      const set = new Set(
        select ? [...prev, ...pageIds] : prev.filter((id) => !pageIds.includes(id)),
      );
      return [...set];
    });
  // Changement de page / tri / filtre : la sélection courante est abandonnée.
  const handleOffsetChange = (offset: number) => {
    setSelectedIds([]);
    setOffset(offset);
  };
  // Tri serveur : par défaut la date de création décroissante (plus récentes
  // d'abord). La réinitialisation de la pagination au tri est gérée par le tableau.
  const [sort, setSort] = useState<{ field: SortField; order: "asc" | "desc" }>({
    field: "ingested_at",
    order: "desc",
  });
  const handleSort = (field: SortField) => {
    setSort((s) =>
      s.field === field
        ? { field, order: s.order === "asc" ? "desc" : "asc" }
        : { field, order: "asc" },
    );
  };

  // Filtres entreprise / source débouncés : les inputs restent instantanés, le
  // fetch n'a lieu qu'après 300 ms sans frappe.
  const debouncedCompany = useDebouncedValue(company, 300);
  const debouncedSource = useDebouncedValue(source, 300);

  // Profils (pour l'icône « + » du détail, profil actif par défaut) — inutile
  // sur la liste des offres actives (le détail s'ouvre sans profil ciblé).
  const profiles = useQuery({
    queryKey: ["profiles"],
    queryFn: api.getProfiles,
    enabled: archived,
  });
  const defaultProfileId =
    profiles.data?.find((p) => p.is_active)?.id ??
    profiles.data?.[0]?.id ??
    null;

  // Détail ciblé : par défaut le meilleur score (1er de la liste) ; sans match,
  // le profil actif. Un clic direct sur un score cible le profil correspondant.
  const detailHref = (
    id: number,
    scores: { candidate_profile_id: number }[],
  ) => {
    const pid = scores[0]?.candidate_profile_id ?? defaultProfileId;
    return pid != null ? `/offers/${id}?candidate_profile_id=${pid}` : `/offers/${id}`;
  };

  const offers = useQuery({
    queryKey: [
      "offers",
      { archived, company: debouncedCompany, source: debouncedSource, offset, sort },
    ],
    queryFn: () =>
      api.getOffers({
        limit: PAGE_SIZE,
        offset,
        archived,
        company: debouncedCompany.trim() || undefined,
        source: debouncedSource.trim() || undefined,
        sortBy: sort.field,
        order: sort.order,
      }),
  });

  const invalidateOffers = (client: QueryClient) => {
    client.invalidateQueries({ queryKey: ["offers"] });
  };
  // Archivage en masse (page actives : `!archived`) / désarchivage (page
  // archivées : `archived`).
  const bulk = useMutation({
    mutationFn: async () => {
      const results = await Promise.allSettled(
        selectedIds.map((id) => api.archiveOffer(id, !archived)),
      );
      // Un échec individuel (ex. offre déjà archivée/supprimée entre-temps) ne
      // doit pas annuler les autres : on tente tout, puis on signale les
      // échecs — la liste est rafraîchie dans tous les cas (onSuccess).
      const failed = results.filter(
        (r): r is PromiseRejectedResult => r.status === "rejected",
      );
      if (failed.length > 0) {
        const sample = failed[0].reason as { message?: string } | undefined;
        throw new Error(
          `${failed.length} offre(s) non ${archived ? "désarchivée(s)" : "archivée(s)"}` +
            (sample?.message ? ` : ${sample.message}` : ""),
        );
      }
      return results;
    },
    onSuccess: () => {
      setSelectedIds([]);
      invalidateOffers(qc);
      // Retour à la première page : sans cela, archiver en masse sur une
      // dernière page (ex. 1 offre restante) laisserait l'offset inchangé et
      // afficherait « Aucune offre » alors qu'il reste des offres plus tôt.
      setOffset(0);
    },
  });

  // Ajout d'offres depuis une URL : l'API récupère la page (Playwright) puis
  // extrait la ou les offres via le LLM (synchrone, spinner dans la modale,
  // jusqu'à `max_offers` pour une liste). `source` (optionnel) : contenu de la
  // page collé par l'utilisateur — présent, il remplace le fetch (offre unique,
  // l'URL n'est jamais récupérée), ce qui débloque les sites anti-bot sans
  // contournement automatisé. À la réussite, la modale reste ouverte avec le
  // résumé (`addResult`), la liste est rafraîchie et on revient à la première
  // page.
  const addOffer = useMutation({
    mutationFn: ({
      url,
      max_offers,
      source,
    }: {
      url: string;
      max_offers: number;
      source?: string;
    }) => api.addOfferFromUrl(url, max_offers, source),
    onSuccess: (data) => {
      setAddResult(data);
      invalidateOffers(qc);
      setOffset(0);
    },
  });

  const total = offers.data?.total ?? 0;
  const bulkError = bulk.error?.message;

  return (
    <div>
      <div>
        <h1 className="text-xl font-semibold text-zinc-900">
          {archived ? "Offres archivées" : "Offres"}
        </h1>
        <p className="mt-1 text-sm text-zinc-500">{total} offre(s)</p>
      </div>

      {/* Filtres */}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <div className="relative">
          <input
            type="text"
            value={company}
            onChange={(e) => {
              setCompany(e.target.value);
              setOffset(0);
              setSelectedIds([]);
            }}
            placeholder="Entreprise"
            className="rounded-md border border-zinc-300 py-1.5 pl-3 pr-8 text-sm"
          />
          {company !== "" && (
            <button
              type="button"
              onClick={() => {
                setCompany("");
                setOffset(0);
                setSelectedIds([]);
              }}
              aria-label="Effacer le filtre entreprise"
              className="absolute inset-y-0 right-0 flex items-center px-2 text-zinc-400 transition-colors hover:text-zinc-700"
            >
              <svg viewBox="0 0 20 20" className="h-4 w-4" aria-hidden="true">
                <path
                  d="M6 6l8 8M14 6l-8 8"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          )}
        </div>
        <div className="relative">
          <input
            type="text"
            value={source}
            onChange={(e) => {
              setSource(e.target.value);
              setOffset(0);
              setSelectedIds([]);
            }}
            placeholder="Source"
            className="rounded-md border border-zinc-300 py-1.5 pl-3 pr-8 text-sm"
          />
          {source !== "" && (
            <button
              type="button"
              onClick={() => {
                setSource("");
                setOffset(0);
                setSelectedIds([]);
              }}
              aria-label="Effacer le filtre source"
              className="absolute inset-y-0 right-0 flex items-center px-2 text-zinc-400 transition-colors hover:text-zinc-700"
            >
              <svg viewBox="0 0 20 20" className="h-4 w-4" aria-hidden="true">
                <path
                  d="M6 6l8 8M14 6l-8 8"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Actions : à gauche la bascule en masse (si des offres sont listées),
          à droite l'ajout manuel par URL — réservé aux offres actives, visible
          même lorsque la liste est vide. */}
      <div className="mt-4 flex items-center justify-between">
        {offers.data && offers.data.items.length > 0 && (
          <Button
            variant={archived ? "success" : "danger"}
            disabled={selectedIds.length === 0 || bulk.isPending}
            onClick={() => bulk.mutate()}
          >
            {archived ? "Désarchiver" : "Archiver"} ({selectedIds.length})
          </Button>
        )}
        {!archived && (
          <div className="ml-auto">
            <Button
              variant="primary"
              onClick={() => {
                setAddResult(null);
                setShowAddModal(true);
              }}
            >
              Ajouter des offres d&apos;emploi
            </Button>
          </div>
        )}
      </div>

      {bulkError && (
        <div className="mt-4">
          <ErrorBox message={bulkError} />
        </div>
      )}
      {offers.isLoading && <Spinner />}
      {offers.error && <ErrorBox message={offers.error.message} />}
      {offers.data && offers.data.items.length === 0 && (
        <EmptyState>
          {archived ? "Aucune offre archivée." : "Aucune offre."}
        </EmptyState>
      )}

      {offers.data && offers.data.items.length > 0 && (
        <OffersTable
          items={offers.data.items}
          total={offers.data.total}
          limit={PAGE_SIZE}
          offset={offset}
          caption={archived ? "Offres archivées" : "Offres"}
          sort={sort}
          onSort={handleSort}
          onOffsetChange={handleOffsetChange}
          detailHref={(o) => detailHref(o.id, o.scores)}
          defaultProfileId={defaultProfileId}
          selectable
          selectedIds={selectedIds}
          onToggleSelect={toggleSelect}
          onToggleSelectPage={toggleSelectPage}
        />
      )}

      <AddOfferModal
        open={showAddModal}
        onClose={() => {
          setAddResult(null);
          setShowAddModal(false);
        }}
        onAdd={(url, maxOffers, source) =>
          addOffer.mutate({ url, max_offers: maxOffers, source })
        }
        isPending={addOffer.isPending}
        error={addOffer.error?.message ?? null}
        result={addResult}
      />
    </div>
  );
}
