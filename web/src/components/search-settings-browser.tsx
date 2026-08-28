"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  SearchAgentRunResult,
  SearchParameter,
  SearchParameterInput,
} from "@/lib/api";
import { Button, EmptyState, ErrorBox, Spinner } from "@/components/ui";
import { SearchSettingsTable } from "@/components/search-settings-table";
import { SearchParameterFormModal } from "@/components/search-parameter-form-modal";
import { ConfirmDeleteModal } from "@/components/confirm-delete-modal";

// Résumé lisible d'une exécution de l'agent de recherche : recherches traitées,
// offres ajoutées / déjà présentes, et échecs par catégorie (omis si nuls).
function runSummary(r: SearchAgentRunResult): string {
  const parts = [
    `${r.succeeded}/${r.total} recherche(s) traitée(s)`,
    `${r.added_offers} offre(s) ajoutée(s)`,
    `${r.already_present} déjà présente(s)`,
  ];
  if (r.duplicates) parts.push(`${r.duplicates} doublon(s)`);
  if (r.scraping_failed) parts.push(`${r.scraping_failed} échec(s) de récupération`);
  if (r.llm_failed) parts.push(`${r.llm_failed} échec(s) LLM`);
  if (r.other_failed) parts.push(`${r.other_failed} erreur(s)`);
  return parts.join(" · ");
}

// Résumé lisible d'un lancement unitaire : compteurs d'offres, sans le « X/Y
// traitées » — une seule recherche est en jeu et son titre/source sont déjà
// affichés dans la bannière.
function runOneSummary(r: SearchAgentRunResult): string {
  const parts = [
    `${r.added_offers} offre(s) ajoutée(s)`,
    `${r.already_present} déjà présente(s)`,
  ];
  if (r.duplicates) parts.push(`${r.duplicates} doublon(s)`);
  if (r.scraping_failed) parts.push(`${r.scraping_failed} échec(s) de récupération`);
  if (r.llm_failed) parts.push(`${r.llm_failed} échec(s) LLM`);
  if (r.other_failed) parts.push(`${r.other_failed} erreur(s)`);
  return parts.join(" · ");
}

// Navigateur des « Recherches sauvegardées » : critères de recherche
// sauvegardés (titre, source, URL) avec ajout, édition (clic sur une ligne) et
// suppression (avec confirmation). CRUD simple via TanStack Query ; la liste est
// rafraîchie à chaque mutation via l'invalidation du queryKey. Le bouton
// « Exécuter » déclenche l'agent de recherche (même pipeline que le DAG) et
// affiche le résumé de l'ingestion dans une bannière ; le triangle vert de
// chaque ligne lance unitairement cette recherche (active ou non).
export function SearchSettingsBrowser() {
  const qc = useQueryClient();
  // Formulaire d'ajout ouvert / paramètre en cours d'édition / de suppression.
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<SearchParameter | null>(null);
  const [deleting, setDeleting] = useState<SearchParameter | null>(null);

  const params = useQuery({
    queryKey: ["search-parameters"],
    queryFn: api.getSearchParameters,
  });

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["search-parameters"] });

  // La réussite d'une création ou d'une modification referme le formulaire
  // (les données sont immédiatement visibles dans la liste) et rafraîchit la
  // liste ; la suppression referme la confirmation.
  const create = useMutation({
    mutationFn: (data: SearchParameterInput) => api.createSearchParameter(data),
    onSuccess: () => {
      setShowForm(false);
      setEditing(null);
      invalidate();
    },
  });
  const update = useMutation({
    mutationFn: ({ id, data }: { id: number; data: SearchParameterInput }) =>
      api.updateSearchParameter(id, data),
    onSuccess: () => {
      setShowForm(false);
      setEditing(null);
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteSearchParameter(id),
    onSuccess: () => {
      setDeleting(null);
      invalidate();
    },
  });

  // Exécution immédiate de l'agent de recherche (même pipeline que le DAG
  // search_parameters_agent). Le succès invalide la liste des offres — de
  // nouvelles offres ont pu être ingérées.
  const run = useMutation({
    mutationFn: () => api.runSearchAgent(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["offers"] }),
  });

  // Lancement unitaire d'une recherche (triangle vert par ligne), active ou
  // non — même pipeline que l'exécution globale. Un seul run à la fois (global
  // ou unitaire) : les autres déclencheurs sont désactivés pendant l'exécution.
  const runOne = useMutation({
    mutationFn: ({ id }: { id: number; title: string; source: string }) =>
      api.runSearchParameter(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["offers"] }),
  });

  // Activation / désactivation d'un paramètre : un paramètre inactif est ignoré
  // par l'agent de recherche (DAG et bouton Exécuter).
  const setActive = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      active
        ? api.activateSearchParameter(id)
        : api.deactivateSearchParameter(id),
    onSuccess: () => invalidate(),
  });

  const closeForm = () => {
    setShowForm(false);
    setEditing(null);
  };

  return (
    <div>
      <div>
        <h1 className="text-xl font-semibold text-zinc-900">
          Recherches sauvegardées
        </h1>
        <p className="mt-1 text-sm text-zinc-500">
          {params.data?.length ?? 0} recherche(s)
        </p>
      </div>

      {run.isPending && (
        <div className="mt-4 rounded-md border border-zinc-200 bg-zinc-50 px-4 py-3 text-sm text-zinc-600">
          Exécution de l&apos;agent de recherche en cours…
        </div>
      )}
      {run.isSuccess && run.data && (
        <div className="mt-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {runSummary(run.data)}
        </div>
      )}
      {run.isError && (
        <div className="mt-4">
          <ErrorBox message={run.error.message} />
        </div>
      )}

      {runOne.isPending && runOne.variables && (
        <div className="mt-4 rounded-md border border-zinc-200 bg-zinc-50 px-4 py-3 text-sm text-zinc-600">
          Exécution de la recherche « {runOne.variables.title} » en cours…
        </div>
      )}
      {runOne.isSuccess && runOne.data && runOne.variables && (
        <div className="mt-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          Recherche « {runOne.variables.title} » ({runOne.variables.source}) :{" "}
          {runOneSummary(runOne.data)}
        </div>
      )}
      {runOne.isError && (
        <div className="mt-4">
          <ErrorBox message={runOne.error.message} />
        </div>
      )}

      <div className="mt-4 flex items-center justify-between gap-2">
        <Button
          variant="success"
          onClick={() => run.mutate()}
          disabled={run.isPending || runOne.isPending}
        >
          {/* Triangle de lecture : action « exécuter » l'agent. */}
          <svg
            aria-hidden="true"
            viewBox="0 0 16 16"
            fill="currentColor"
            className="h-3.5 w-3.5"
          >
            <path d="M5.5 3.5l7 4.5-7 4.5z" />
          </svg>
          {run.isPending ? "Exécution…" : "Exécuter"}
        </Button>
        <Button
          variant="primary"
          onClick={() => {
            setEditing(null);
            setShowForm(true);
          }}
        >
          Ajouter
        </Button>
      </div>

      {params.isLoading && <Spinner />}
      {params.error && <ErrorBox message={params.error.message} />}
      {params.data && params.data.length === 0 && (
        <EmptyState>Aucune recherche sauvegardée.</EmptyState>
      )}

      {params.data && params.data.length > 0 && (
        <SearchSettingsTable
          items={params.data}
          onEdit={(p) => {
            setShowForm(false);
            setEditing(p);
          }}
          onDelete={setDeleting}
          onToggleActive={(p) =>
            setActive.mutate({ id: p.id, active: !p.is_active })
          }
          onRun={(p) =>
            runOne.mutate({ id: p.id, title: p.title, source: p.source })
          }
          disabled={setActive.isPending}
          runDisabled={run.isPending || runOne.isPending}
          runningId={runOne.isPending ? (runOne.variables?.id ?? null) : null}
        />
      )}

      {/* key={editing?.id ?? "new"} : le remount garantit que l'état local du
          formulaire repart de `initial` à chaque ouverture. */}
      <SearchParameterFormModal
        key={editing?.id ?? "new"}
        open={showForm || editing !== null}
        initial={editing}
        onClose={closeForm}
        onSubmit={(data) =>
          editing ? update.mutate({ id: editing.id, data }) : create.mutate(data)
        }
        isPending={editing ? update.isPending : create.isPending}
        error={
          editing
            ? (update.error?.message ?? null)
            : (create.error?.message ?? null)
        }
      />

      <ConfirmDeleteModal
        open={deleting !== null}
        parameter={deleting}
        onClose={() => setDeleting(null)}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.id);
        }}
        isPending={remove.isPending}
        error={remove.error?.message ?? null}
      />
    </div>
  );
}
