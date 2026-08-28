"use client";

import { useState } from "react";
import { Button, ErrorBox, Modal } from "@/components/ui";
import type { AddOffersResult } from "@/lib/api";

// Bornes du slider « nombre maximal d'offres à récupérer » (alignées sur le
// contrat API : 1 → 20, défaut 5). Le slider ne vaut que pour une **liste**
// récupérée par fetch : il est désactivé dès qu'un contenu collé est fourni
// (offre unique, le contenu remplace la récupération automatique de la page).
const MAX_OFFERS_MIN = 1;
const MAX_OFFERS_MAX = 20;
const DEFAULT_MAX_OFFERS = 5;

// Petit spinner animé (cercle tournant) affiché pendant l'ingestion : plus
// visible qu'un simple libellé de bouton.
function LoadingSpinner() {
  return (
    <svg
      className="h-10 w-10 animate-spin text-emerald-600"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  );
}

// Modale « Ajouter des offres d'emploi » : saisie d'une URL (+ nombre maximal
// d'offres à récupérer pour une liste), avec un champ « Contenu de la page »
// **optionnel** : rempli, il remplace la récupération automatique (offre
// unique) — l'URL sert alors de clé de dédoublonnage et n'est jamais
// récupérée, ce qui débloque les sites anti-bot sans contournement automatisé.
// L'envoi est synchrone, orchestré par le parent (mutation react-query) :
// l'état d'envoi (``isPending``), l'erreur (``error``) et le résultat
// (``result``) y sont décidés, ce qui garde ce composant purement présentiel
// et testable.
export function AddOfferModal({
  open,
  onClose,
  onAdd,
  isPending,
  error,
  result,
}: {
  open: boolean;
  onClose: () => void;
  onAdd: (url: string, maxOffers: number, source?: string) => void;
  isPending: boolean;
  error: string | null;
  result: AddOffersResult | null;
}) {
  const [url, setUrl] = useState("");
  const [maxOffers, setMaxOffers] = useState(DEFAULT_MAX_OFFERS);
  const [source, setSource] = useState("");
  // « Contenu collé » actif : le contenu remplace le fetch → offre unique, le
  // slider (nombre d'offres d'une liste) n'a plus de sens.
  const isSourceMode = source.trim() !== "";

  // La fermeture (annulation ou succès) remet le formulaire à son état initial
  // pour une prochaine ouverture propre. Pendant l'envoi, la modale est
  // **verrouillée** : Escape, clic sur le fond et bouton ✕ sont ignorés —
  // l'ingestion synchrone (Playwright + LLM) ne peut pas être interrompue côté
  // serveur.
  const handleClose = () => {
    if (isPending) return;
    setUrl("");
    setMaxOffers(DEFAULT_MAX_OFFERS);
    setSource("");
    onClose();
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isPending) return;
    const value = url.trim();
    if (!value) return;
    // Source transmis tel quel (espaces de tête/taille conservés) uniquement
    // s'il contient du texte ; absent → récupération automatique de la page.
    onAdd(value, maxOffers, isSourceMode ? source : undefined);
  };

  // Pendant l'ingestion, le formulaire est remplacé par un écran de chargement
  // clairement visible (spinner animé + message), pour ne pas laisser croire à
  // un blocage.
  if (isPending) {
    return (
      <Modal open={open} onClose={handleClose} title="Ajouter des offres d'emploi">
        <div className="flex flex-col items-center gap-5 py-12 text-center">
          <LoadingSpinner />
          <div>
            <p className="text-sm font-medium text-zinc-700">
              Récupération de la page et extraction des offres en cours…
            </p>
            <p className="mt-1 text-xs text-zinc-400">
              Veuillez patienter — ne fermez pas cette fenêtre.
            </p>
          </div>
        </div>
      </Modal>
    );
  }

  // Écran de succès : la modale reste ouverte avec un résumé (une page d'offre
  // unique ajoute 1 offre ; une liste peut en ajouter plusieurs, certaines déjà
  // présentes). Le bouton « Fermer » réinitialise le formulaire.
  if (result) {
    return (
      <Modal open={open} onClose={handleClose} title="Ajouter des offres d'emploi">
        <div className="flex flex-col items-center gap-5 py-10 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100">
            <svg
              viewBox="0 0 20 20"
              className="h-6 w-6 text-emerald-600"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M4 10l4 4 8-8"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <div>
            <p className="text-sm font-medium text-zinc-700">
              {result.added} offre{result.added > 1 ? "s" : ""} ajoutée
              {result.added > 1 ? "s" : ""}
            </p>
            {result.already_present > 0 && (
              <p className="mt-1 text-xs text-zinc-500">
                {result.already_present} déjà présente
                {result.already_present > 1 ? "s" : ""} en base
              </p>
            )}
          </div>
          <Button variant="primary" onClick={handleClose}>
            Fermer
          </Button>
        </div>
      </Modal>
    );
  }

  const canSubmit = url.trim() !== "";

  return (
    <Modal open={open} onClose={handleClose} title="Ajouter des offres d'emploi">
      <form onSubmit={handleSubmit} className="mt-4 space-y-3">
        <div>
          <label
            htmlFor="offer-url"
            className="block text-sm font-medium text-zinc-700"
          >
            URL de l&apos;offre
          </label>
          <input
            id="offer-url"
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://…"
            disabled={isPending}
            autoFocus
            className="w-full rounded-md border border-zinc-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label
            htmlFor="offer-max"
            className="block text-sm font-medium text-zinc-700"
          >
            Nombre maximal d&apos;offres : {maxOffers}
          </label>
          <input
            id="offer-max"
            type="range"
            min={MAX_OFFERS_MIN}
            max={MAX_OFFERS_MAX}
            value={maxOffers}
            onChange={(e) => setMaxOffers(Number(e.target.value))}
            disabled={isPending || isSourceMode}
            className="mt-2 w-full accent-emerald-600"
          />
          <p className="mt-1 text-xs text-zinc-400">
            {isSourceMode
              ? "Offre unique : le contenu collé remplace la récupération automatique de la page."
              : "Pour une liste d'offres, seules les offres nouvelles (non déjà en base) sont ajoutées, jusqu'à " +
                maxOffers +
                "."}
          </p>
        </div>
        <div>
          <label
            htmlFor="offer-source"
            className="block text-sm font-medium text-zinc-700"
          >
            Contenu de la page (optionnel)
          </label>
          <textarea
            id="offer-source"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="Collez le code source (HTML) ou le texte de la page, si la récupération automatique échoue…"
            rows={8}
            disabled={isPending}
            className="w-full resize-y rounded-md border border-zinc-300 px-3 py-1.5 text-sm"
          />
          <p className="mt-1 text-xs text-zinc-400">
            Rempli, il remplace la récupération automatique (sites protégés par
            un anti-bot) : l&apos;URL sert de clé de dédoublonnage et
            n&apos;est jamais récupérée par le serveur. Les styles et scripts
            du code source sont ignorés.
          </p>
        </div>
        {error && <ErrorBox message={error} />}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={handleClose} disabled={isPending}>
            Annuler
          </Button>
          <Button type="submit" disabled={isPending || !canSubmit}>
            {isPending ? "Ajout en cours…" : "Valider"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
