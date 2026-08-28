import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SearchSettingsTable } from "@/components/search-settings-table";
import type { SearchParameter } from "@/lib/api";

const param: SearchParameter = {
  id: 1,
  title: "Data Engineer",
  source: "hellowork",
  url: "https://example.com/jobs",
  max_offers: 5,
  is_active: true,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-01T10:00:00Z",
};

function renderTable({
  items = [param],
  runDisabled = false,
  runningId = null,
}: {
  items?: SearchParameter[];
  runDisabled?: boolean;
  runningId?: number | null;
} = {}) {
  const onEdit = vi.fn();
  const onDelete = vi.fn();
  const onToggleActive = vi.fn();
  const onRun = vi.fn();
  render(
    <SearchSettingsTable
      items={items}
      onEdit={onEdit}
      onDelete={onDelete}
      onToggleActive={onToggleActive}
      onRun={onRun}
      runDisabled={runDisabled}
      runningId={runningId}
    />,
  );
  return { onEdit, onDelete, onToggleActive, onRun };
}

describe("SearchSettingsTable", () => {
  it("affiche les colonnes (Lancer, Titre, Source, URL, Max offres, Statut) et les valeurs", () => {
    renderTable();

    expect(
      screen.getByRole("columnheader", { name: "Lancer" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Titre" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Source" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "URL" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Max offres" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Statut" }),
    ).toBeInTheDocument();

    expect(screen.getByText("Data Engineer")).toBeInTheDocument();
    expect(screen.getByText("hellowork")).toBeInTheDocument();
    expect(screen.getByText("https://example.com/jobs")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("Actif")).toBeInTheDocument();
    // Un triangle de lancement par ligne, libellé avec le titre.
    expect(
      screen.getByRole("button", { name: "Lancer la recherche « Data Engineer »" }),
    ).toBeInTheDocument();
  });

  it("déclenche onRun sans onEdit au clic sur le triangle", async () => {
    const user = userEvent.setup();
    const { onRun, onEdit } = renderTable();

    await user.click(
      screen.getByRole("button", { name: "Lancer la recherche « Data Engineer »" }),
    );

    expect(onRun).toHaveBeenCalledWith(param);
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("désactive les triangles pendant un run (runDisabled)", () => {
    renderTable({ runDisabled: true });

    expect(
      screen.getByRole("button", { name: "Lancer la recherche « Data Engineer »" }),
    ).toBeDisabled();
  });

  it("laisse le lancement possible sur une recherche inactive", () => {
    // runDisabled=false : même inactive, le triangle reste actif — le lancement
    // unitaire ignore is_active (test ponctuel, le statut est inchangé).
    renderTable({ items: [{ ...param, is_active: false }] });

    expect(
      screen.getByRole("button", { name: "Lancer la recherche « Data Engineer »" }),
    ).toBeEnabled();
  });

  it("garde le bouton pendant l'exécution de la ligne (spinner)", () => {
    renderTable({ runningId: param.id });

    // Le bouton est toujours présent (le triangle devient un spinner), même
    // aria-label pour les lecteurs d'écran.
    expect(
      screen.getByRole("button", { name: "Lancer la recherche « Data Engineer »" }),
    ).toBeInTheDocument();
  });

  it("affiche le statut de chaque paramètre (Actif / Inactif)", () => {
    renderTable({
      items: [param, { ...param, id: 2, is_active: false }],
    });

    expect(screen.getByText("Actif")).toBeInTheDocument();
    expect(screen.getByText("Inactif")).toBeInTheDocument();
    // Le toggle d'un paramètre inactif est libellé « Activer ».
    expect(
      screen.getByRole("button", { name: "Activer Data Engineer" }),
    ).toBeInTheDocument();
  });

  it("déclenche onToggleActive sans onEdit au clic sur le toggle", async () => {
    const user = userEvent.setup();
    const { onToggleActive, onEdit } = renderTable();

    await user.click(
      screen.getByRole("button", { name: "Désactiver Data Engineer" }),
    );

    expect(onToggleActive).toHaveBeenCalledWith(param);
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("déclenche onEdit au clic sur une ligne", async () => {
    const user = userEvent.setup();
    const { onEdit } = renderTable();

    await user.click(screen.getByText("Data Engineer"));

    expect(onEdit).toHaveBeenCalledWith(param);
  });

  it("déclenche onDelete sans onEdit au clic sur le bouton de suppression", async () => {
    const user = userEvent.setup();
    const { onEdit, onDelete } = renderTable();

    await user.click(
      screen.getByRole("button", { name: "Supprimer Data Engineer" }),
    );

    expect(onDelete).toHaveBeenCalledWith(param);
    expect(onEdit).not.toHaveBeenCalled();
  });
});
