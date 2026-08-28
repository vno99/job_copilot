"use client";

import { Button, ErrorBox, Modal } from "@/components/ui";
import type { SearchParameter } from "@/lib/api";

// Confirmation de suppression d'une recherche sauvegardée. Présentielle :
// l'état d'envoi (``isPending``) et l'erreur (``error``) viennent de
// l'orchestrateur ; à la réussite, la modale est fermée par le parent.
export function ConfirmDeleteModal({
  open,
  parameter,
  onClose,
  onConfirm,
  isPending,
  error,
}: {
  open: boolean;
  parameter: SearchParameter | null;
  onClose: () => void;
  onConfirm: () => void;
  isPending: boolean;
  error: string | null;
}) {
  return (
    <Modal open={open} onClose={onClose} title="Supprimer cette recherche ?">
      <div className="space-y-4">
        <p className="text-sm text-zinc-700">
          Êtes-vous sûr de vouloir supprimer « {parameter?.title ?? ""} » ? Cette
          action est définitive.
        </p>
        {error && <ErrorBox message={error} />}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={isPending}>
            Annuler
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={isPending}>
            {isPending ? "Suppression…" : "Supprimer"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
