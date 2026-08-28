"use client";

import { useState } from "react";
import { Button, ErrorBox, Modal } from "@/components/ui";
import type { SearchParameter, SearchParameterInput } from "@/lib/api";

// Bornes du slider « nombre maximal d'offres » (alignées sur le contrat API :
// 1 → 20, défaut 5 — mêmes bornes que l'ajout d'offres par URL).
const MAX_OFFERS_MIN = 1;
const MAX_OFFERS_MAX = 20;
const DEFAULT_MAX_OFFERS = 5;

// Modale de formulaire partagée ajout / édition d'une recherche sauvegardée.
// Présentielle : l'orchestrateur décide de l'état d'envoi (``isPending``) et de
// l'erreur (``error``, ex. 409 URL déjà utilisée). Le parent force le remount
// via ``key`` et l'état local est remis à ``initial`` à la fermeture, pour une
// réouverture propre.
export function SearchParameterFormModal({
  open,
  initial,
  onClose,
  onSubmit,
  isPending,
  error,
}: {
  open: boolean;
  initial: SearchParameter | null;
  onClose: () => void;
  onSubmit: (data: SearchParameterInput) => void;
  isPending: boolean;
  error: string | null;
}) {
  const [form, setForm] = useState({
    title: initial?.title ?? "",
    source: initial?.source ?? "",
    url: initial?.url ?? "",
    maxOffers: initial?.max_offers ?? DEFAULT_MAX_OFFERS,
  });

  // La fermeture remet le formulaire à son état initial (depuis ``initial``)
  // pour une prochaine ouverture propre.
  const handleClose = () => {
    setForm({
      title: initial?.title ?? "",
      source: initial?.source ?? "",
      url: initial?.url ?? "",
      maxOffers: initial?.max_offers ?? DEFAULT_MAX_OFFERS,
    });
    onClose();
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      title: form.title.trim(),
      source: form.source.trim(),
      url: form.url.trim(),
      max_offers: form.maxOffers,
    });
  };

  const field = "w-full rounded-md border border-zinc-300 px-3 py-1.5 text-sm";

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={initial ? "Modifier la recherche" : "Ajouter une recherche"}
    >
      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label
            htmlFor="search-parameter-title"
            className="block text-sm font-medium text-zinc-700"
          >
            Titre
          </label>
          <input
            id="search-parameter-title"
            type="text"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            autoFocus
            disabled={isPending}
            className={field}
          />
        </div>
        <div>
          <label
            htmlFor="search-parameter-source"
            className="block text-sm font-medium text-zinc-700"
          >
            Source
          </label>
          <input
            id="search-parameter-source"
            type="text"
            value={form.source}
            onChange={(e) => setForm({ ...form, source: e.target.value })}
            disabled={isPending}
            className={field}
          />
        </div>
        <div>
          <label
            htmlFor="search-parameter-url"
            className="block text-sm font-medium text-zinc-700"
          >
            URL
          </label>
          <input
            id="search-parameter-url"
            type="text"
            value={form.url}
            onChange={(e) => setForm({ ...form, url: e.target.value })}
            placeholder="https://…"
            disabled={isPending}
            className={field}
          />
        </div>
        <div>
          <label
            htmlFor="search-parameter-max-offers"
            className="block text-sm font-medium text-zinc-700"
          >
            Nombre maximal d&apos;offres : {form.maxOffers}
          </label>
          <input
            id="search-parameter-max-offers"
            type="range"
            min={MAX_OFFERS_MIN}
            max={MAX_OFFERS_MAX}
            value={form.maxOffers}
            onChange={(e) => setForm({ ...form, maxOffers: Number(e.target.value) })}
            disabled={isPending}
            className="mt-2 w-full accent-emerald-600"
          />
          <p className="mt-1 text-xs text-zinc-400">
            Pour une liste d&apos;offres, seules les offres nouvelles (non déjà en
            base) sont ajoutées, jusqu&apos;à {form.maxOffers}.
          </p>
        </div>
        {error && <ErrorBox message={error} />}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={handleClose} disabled={isPending}>
            Annuler
          </Button>
          <Button type="submit" disabled={isPending}>
            {isPending ? "Enregistrement…" : "Enregistrer"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
