import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SearchSettingsBrowser } from "@/components/search-settings-browser";
import type { SearchAgentRunResult, SearchParameter } from "@/lib/api";

// Mocks du client API : les méthodes du CRUD des paramètres, l'activation /
// désactivation et les exécutions (globale et unitaire) de l'agent sont
// espionnables.
const {
  getSearchParametersMock,
  createSearchParameterMock,
  updateSearchParameterMock,
  deleteSearchParameterMock,
  activateSearchParameterMock,
  deactivateSearchParameterMock,
  runSearchAgentMock,
  runSearchParameterMock,
} = vi.hoisted(() => ({
  getSearchParametersMock: vi.fn(),
  createSearchParameterMock: vi.fn(),
  updateSearchParameterMock: vi.fn(),
  deleteSearchParameterMock: vi.fn(),
  activateSearchParameterMock: vi.fn(),
  deactivateSearchParameterMock: vi.fn(),
  runSearchAgentMock: vi.fn(),
  runSearchParameterMock: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    getSearchParameters: getSearchParametersMock,
    createSearchParameter: createSearchParameterMock,
    updateSearchParameter: updateSearchParameterMock,
    deleteSearchParameter: deleteSearchParameterMock,
    activateSearchParameter: activateSearchParameterMock,
    deactivateSearchParameter: deactivateSearchParameterMock,
    runSearchAgent: runSearchAgentMock,
    runSearchParameter: runSearchParameterMock,
  },
}));

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

// Résumé d'une exécution de l'agent : 2 paramètres traités, 3 offres ajoutées,
// 1 déjà présente, aucun échec (les compteurs nuls sont omis du résumé).
const runResult: SearchAgentRunResult = {
  total: 2,
  succeeded: 2,
  duplicates: 0,
  scraping_failed: 0,
  llm_failed: 0,
  other_failed: 0,
  added_offers: 3,
  already_present: 1,
  parameters: [
    {
      id: 1,
      title: "Data Engineer",
      source: "hellowork",
      url: "https://example.com/jobs",
      max_offers: 5,
      status: "ok",
      added: 3,
      already_present: 1,
    },
    {
      id: 2,
      title: "Data Analyst",
      source: "hellowork",
      url: "https://example.com/analyst",
      max_offers: 5,
      status: "ok",
    },
  ],
};

// Résumé d'un lancement unitaire : une seule recherche, 1 offre ajoutée et
// 1 déjà présente — la bannière affiche le titre et la source de la ligne.
const runOneResult: SearchAgentRunResult = {
  total: 1,
  succeeded: 1,
  duplicates: 0,
  scraping_failed: 0,
  llm_failed: 0,
  other_failed: 0,
  added_offers: 1,
  already_present: 1,
  parameters: [
    {
      id: 1,
      title: "Data Engineer",
      source: "hellowork",
      url: "https://example.com/jobs",
      max_offers: 5,
      status: "ok",
      added: 1,
      already_present: 1,
    },
  ],
};

// QueryClient par test (état isolé, retry désactivé pour des échecs rapides).
function renderBrowser() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <SearchSettingsBrowser />
    </QueryClientProvider>,
  );
}

describe("SearchSettingsBrowser", () => {
  beforeEach(() => {
    getSearchParametersMock.mockReset();
    createSearchParameterMock.mockReset();
    updateSearchParameterMock.mockReset();
    deleteSearchParameterMock.mockReset();
    activateSearchParameterMock.mockReset();
    deactivateSearchParameterMock.mockReset();
    runSearchAgentMock.mockReset();
    runSearchParameterMock.mockReset();
  });

  it("affiche la liste des paramètres et le compteur", async () => {
    getSearchParametersMock.mockResolvedValue([param]);
    renderBrowser();

    expect(
      screen.getByRole("heading", { name: "Recherches sauvegardées" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Data Engineer")).toBeInTheDocument();
    expect(screen.getByText("1 recherche(s)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ajouter" })).toBeInTheDocument();
  });

  it("affiche un état vide quand aucun paramètre", async () => {
    getSearchParametersMock.mockResolvedValue([]);
    renderBrowser();

    expect(
      await screen.findByText("Aucune recherche sauvegardée."),
    ).toBeInTheDocument();
  });

  it("affiche une erreur quand le chargement échoue", async () => {
    getSearchParametersMock.mockRejectedValue(new Error("Base indisponible"));
    renderBrowser();

    expect(await screen.findByText("Base indisponible")).toBeInTheDocument();
  });

  it("ajoute un paramètre via le formulaire (valeurs trimées)", async () => {
    const user = userEvent.setup();
    // Premier fetch : liste vide ; après l'ajout, l'invalidation recharge [param].
    getSearchParametersMock
      .mockResolvedValueOnce([])
      .mockResolvedValue([param]);
    createSearchParameterMock.mockResolvedValue(param);
    renderBrowser();

    await screen.findByText("Aucune recherche sauvegardée.");
    await user.click(screen.getByRole("button", { name: "Ajouter" }));

    // La modale d'ajout s'ouvre, formulaire vide.
    expect(screen.getByText("Ajouter une recherche")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Titre"), "  Data Engineer  ");
    await user.type(screen.getByLabelText("Source"), "hellowork");
    await user.type(screen.getByLabelText("URL"), "https://example.com/jobs");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    // La mutation reçoit les valeurs trimées ; la modale se ferme et la liste
    // rafraîchie affiche le nouveau paramètre.
    await waitFor(() =>
      expect(createSearchParameterMock).toHaveBeenCalledWith({
        title: "Data Engineer",
        source: "hellowork",
        url: "https://example.com/jobs",
        max_offers: 5, // défaut du slider
      }),
    );
    expect(await screen.findByText("Data Engineer")).toBeInTheDocument();
    expect(
      screen.queryByText("Ajouter une recherche"),
    ).not.toBeInTheDocument();
  });

  it("déplace le slider du nombre maximal d'offres avant la création", async () => {
    const user = userEvent.setup();
    getSearchParametersMock.mockResolvedValueOnce([]).mockResolvedValue([param]);
    createSearchParameterMock.mockResolvedValue(param);
    renderBrowser();

    await screen.findByText("Aucune recherche sauvegardée.");
    await user.click(screen.getByRole("button", { name: "Ajouter" }));

    // Le slider est borné 1 → 20 et démarre à la valeur par défaut 5.
    const slider = screen.getByRole("slider", {
      name: "Nombre maximal d'offres : 5",
    });
    fireEvent.change(slider, { target: { value: "12" } });

    await user.type(screen.getByLabelText("Titre"), "Data Engineer");
    await user.type(screen.getByLabelText("Source"), "hellowork");
    await user.type(screen.getByLabelText("URL"), "https://example.com/jobs");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    // La valeur du slider est transmise à la création.
    await waitFor(() =>
      expect(createSearchParameterMock).toHaveBeenCalledWith({
        title: "Data Engineer",
        source: "hellowork",
        url: "https://example.com/jobs",
        max_offers: 12,
      }),
    );
  });

  it("modifie un paramètre au clic sur une ligne (champs pré-remplis)", async () => {
    const user = userEvent.setup();
    getSearchParametersMock
      .mockResolvedValueOnce([param])
      .mockResolvedValue([{ ...param, title: "Data Engineer Senior" }]);
    updateSearchParameterMock.mockResolvedValue({
      ...param,
      title: "Data Engineer Senior",
    });
    renderBrowser();

    await screen.findByText("Data Engineer");
    await user.click(screen.getByText("Data Engineer"));

    // La modale d'édition s'ouvre pré-remplie avec les valeurs du paramètre.
    expect(screen.getByText("Modifier la recherche")).toBeInTheDocument();
    expect(screen.getByLabelText("Titre")).toHaveValue("Data Engineer");
    expect(screen.getByLabelText("Source")).toHaveValue("hellowork");
    expect(screen.getByLabelText("URL")).toHaveValue("https://example.com/jobs");

    await user.clear(screen.getByLabelText("Titre"));
    await user.type(screen.getByLabelText("Titre"), "Data Engineer Senior");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    await waitFor(() =>
      expect(updateSearchParameterMock).toHaveBeenCalledWith(1, {
        title: "Data Engineer Senior",
        source: "hellowork",
        url: "https://example.com/jobs",
        max_offers: 5,
      }),
    );
    expect(
      await screen.findByText("Data Engineer Senior"),
    ).toBeInTheDocument();
  });

  it("supprime un paramètre après confirmation", async () => {
    const user = userEvent.setup();
    getSearchParametersMock
      .mockResolvedValueOnce([param])
      .mockResolvedValue([]);
    deleteSearchParameterMock.mockResolvedValue(undefined);
    renderBrowser();

    await screen.findByText("Data Engineer");

    // Bouton de suppression de la ligne (ne déclenche pas l'édition).
    await user.click(
      screen.getByRole("button", { name: "Supprimer Data Engineer" }),
    );

    // Modale de confirmation.
    expect(
      screen.getByText("Supprimer cette recherche ?"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Êtes-vous sûr de vouloir supprimer « Data Engineer »/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Supprimer" }));

    await waitFor(() =>
      expect(deleteSearchParameterMock).toHaveBeenCalledWith(1),
    );
    // La liste rafraîchie est vide.
    expect(
      await screen.findByText("Aucune recherche sauvegardée."),
    ).toBeInTheDocument();
  });

  it("affiche l'erreur 409 et garde la modale ouverte", async () => {
    const user = userEvent.setup();
    getSearchParametersMock.mockResolvedValue([]);
    createSearchParameterMock.mockRejectedValue(
      new Error("L'URL 'https://example.com/jobs' est déjà utilisée par « X »"),
    );
    renderBrowser();

    await screen.findByText("Aucune recherche sauvegardée.");
    await user.click(screen.getByRole("button", { name: "Ajouter" }));
    await user.type(screen.getByLabelText("Titre"), "Data Engineer");
    await user.type(screen.getByLabelText("Source"), "hellowork");
    await user.type(screen.getByLabelText("URL"), "https://example.com/jobs");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    // L'erreur serveur (detail du 409) est affichée et la modale reste ouverte
    // pour permettre la correction.
    expect(
      await screen.findByText(
        "L'URL 'https://example.com/jobs' est déjà utilisée par « X »",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Titre")).toBeInTheDocument();
  });

  it("exécute l'agent et affiche le résumé de l'ingestion", async () => {
    const user = userEvent.setup();
    getSearchParametersMock.mockResolvedValue([param]);

    // Résolution contrôlée : on vérifie l'état « en cours » avant la fin.
    let resolveRun!: (value: SearchAgentRunResult) => void;
    runSearchAgentMock.mockReturnValue(
      new Promise<SearchAgentRunResult>((resolve) => {
        resolveRun = resolve;
      }),
    );
    renderBrowser();

    await screen.findByText("Data Engineer");
    await user.click(screen.getByRole("button", { name: "Exécuter" }));

    expect(runSearchAgentMock).toHaveBeenCalledTimes(1);
    // Pendant l'exécution : bouton désactivé, libellé « Exécution… » et
    // bannière d'attente affichée.
    expect(screen.getByRole("button", { name: "Exécution…" })).toBeDisabled();
    expect(
      screen.getByText("Exécution de l'agent de recherche en cours…"),
    ).toBeInTheDocument();

    // La résolution affiche le résumé (paramètres traités, offres ajoutées,
    // déjà présentes — les échecs nuls sont omis).
    resolveRun(runResult);
    expect(
      await screen.findByText(
        "2/2 recherche(s) traitée(s) · 3 offre(s) ajoutée(s) · 1 déjà présente(s)",
      ),
    ).toBeInTheDocument();
  });

  it("affiche une erreur si l'exécution de l'agent échoue", async () => {
    const user = userEvent.setup();
    getSearchParametersMock.mockResolvedValue([param]);
    runSearchAgentMock.mockRejectedValue(new Error("LLM indisponible"));
    renderBrowser();

    await screen.findByText("Data Engineer");
    await user.click(screen.getByRole("button", { name: "Exécuter" }));

    expect(await screen.findByText("LLM indisponible")).toBeInTheDocument();
  });

  it("lance unitairement une recherche via le triangle (résumé avec titre et source)", async () => {
    const user = userEvent.setup();
    getSearchParametersMock.mockResolvedValue([param]);
    runSearchParameterMock.mockResolvedValue(runOneResult);
    renderBrowser();

    await screen.findByText("Data Engineer");
    await user.click(
      screen.getByRole("button", {
        name: "Lancer la recherche « Data Engineer »",
      }),
    );

    await waitFor(() => expect(runSearchParameterMock).toHaveBeenCalledWith(1));
    // La bannière enrichie affiche le titre ET la source de la ligne.
    expect(
      await screen.findByText(
        "Recherche « Data Engineer » (hellowork) : 1 offre(s) ajoutée(s) · 1 déjà présente(s)",
      ),
    ).toBeInTheDocument();
  });

  it("désactive les autres déclencheurs et affiche l'attente pendant un lancement unitaire", async () => {
    const user = userEvent.setup();
    getSearchParametersMock.mockResolvedValue([param]);
    // Résolution jamais atteinte : on vérifie l'état « en cours ».
    runSearchParameterMock.mockReturnValue(new Promise(() => {}));
    renderBrowser();

    await screen.findByText("Data Engineer");
    await user.click(
      screen.getByRole("button", {
        name: "Lancer la recherche « Data Engineer »",
      }),
    );

    // Bannière d'attente portant le titre de la recherche lancée.
    expect(
      screen.getByText("Exécution de la recherche « Data Engineer » en cours…"),
    ).toBeInTheDocument();
    // Bouton « Exécuter » global et triangle de la ligne désactivés.
    expect(screen.getByRole("button", { name: "Exécuter" })).toBeDisabled();
    expect(
      screen.getByRole("button", {
        name: "Lancer la recherche « Data Engineer »",
      }),
    ).toBeDisabled();
  });

  it("affiche une erreur si le lancement unitaire échoue", async () => {
    const user = userEvent.setup();
    getSearchParametersMock.mockResolvedValue([param]);
    runSearchParameterMock.mockRejectedValue(new Error("LLM indisponible"));
    renderBrowser();

    await screen.findByText("Data Engineer");
    await user.click(
      screen.getByRole("button", {
        name: "Lancer la recherche « Data Engineer »",
      }),
    );

    expect(await screen.findByText("LLM indisponible")).toBeInTheDocument();
  });

  it("désactive un paramètre via le toggle (ignoré par l'agent)", async () => {
    const user = userEvent.setup();
    // Premier fetch : paramètre actif ; après le toggle, la liste rafraîchie
    // renvoie le paramètre inactif.
    getSearchParametersMock
      .mockResolvedValueOnce([param])
      .mockResolvedValue([{ ...param, is_active: false }]);
    deactivateSearchParameterMock.mockResolvedValue({
      ...param,
      is_active: false,
    });
    renderBrowser();

    await screen.findByText("Data Engineer");
    await user.click(
      screen.getByRole("button", { name: "Désactiver Data Engineer" }),
    );

    await waitFor(() =>
      expect(deactivateSearchParameterMock).toHaveBeenCalledWith(1),
    );
    // La liste rafraîchie affiche le statut « Inactif ».
    expect(await screen.findByText("Inactif")).toBeInTheDocument();
  });
});
