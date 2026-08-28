import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OffersBrowser } from "@/components/offers-browser";
import type { AddOffersResult, JobOfferListItem } from "@/lib/api";

// Mocks du client API : `getOffers` / `getProfiles` / `archiveOffer` /
// `addOfferFromUrl` sont espionnables. La mutation bulk appelle
// `archiveOffer(id, !archived)`, la modale d'ajout appelle
// `addOfferFromUrl(url, maxOffers, source?)` — le `source` (optionnel)
// remplace le fetch de la page côté serveur.
const { getOffersMock, getProfilesMock, archiveOfferMock, addOfferFromUrlMock } =
  vi.hoisted(() => ({
    getOffersMock: vi.fn(),
    getProfilesMock: vi.fn(),
    archiveOfferMock: vi.fn(),
    addOfferFromUrlMock: vi.fn(),
  }));

vi.mock("@/lib/api", () => ({
  api: {
    getOffers: getOffersMock,
    getProfiles: getProfilesMock,
    archiveOffer: archiveOfferMock,
    addOfferFromUrl: addOfferFromUrlMock,
  },
}));

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

// Même mock next/link que offers-table.test.tsx (navigation client prévenue,
// handlers du composant préservés).
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    onClick,
    title,
  }: {
    href: string;
    children: ReactNode;
    onClick?: (e: React.MouseEvent<HTMLAnchorElement>) => void;
    title?: string;
  }) => (
    <a
      href={href}
      onClick={(e) => {
        e.preventDefault();
        onClick?.(e);
      }}
      title={title}
    >
      {children}
    </a>
  ),
}));

const offer: JobOfferListItem = {
  id: 7,
  source: "hellowork",
  title: "Développeur Python",
  company: "Acme",
  location: "Paris - 75",
  contract_type: "CDI",
  published_date: "2026-07-01",
  url: "https://hellowork.com/offre/7",
  ingested_at: "2026-08-01T10:00:00Z",
  archived: false,
  scores: [],
};

const offersResponse = {
  total: 1,
  limit: 25,
  offset: 0,
  items: [offer],
};

// Retour de POST /job-offers/from-url : offre unique ajoutée.
const addResult: AddOffersResult = {
  offers: [offer],
  added: 1,
  already_present: 0,
};

// Retour pour une liste : 1 ajoutée, 1 déjà présente en base.
const addResultList: AddOffersResult = {
  offers: [offer, { ...offer, id: 8, title: "Data Analyst" }],
  added: 1,
  already_present: 1,
};

const profile = {
  id: 1,
  profile_name: "Profil A",
  is_active: true,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-01T10:00:00Z",
};

// QueryClient par test (état isolé, retry désactivé pour des échecs rapides).
function renderBrowser({ archived = false }: { archived?: boolean } = {}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <OffersBrowser archived={archived} />
    </QueryClientProvider>,
  );
}

describe("OffersBrowser", () => {
  beforeEach(() => {
    getOffersMock.mockReset();
    getProfilesMock.mockReset();
    archiveOfferMock.mockReset();
    addOfferFromUrlMock.mockReset();
    pushMock.mockClear();
  });

  it("affiche la liste des offres actives (mode non archivé)", async () => {
    getOffersMock.mockResolvedValue(offersResponse);
    renderBrowser({ archived: false });

    expect(await screen.findByText("Développeur Python")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Offres" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Archiver/ })).toBeInTheDocument();
    // Mode actif : aucun fetch des profils (détail sans profil ciblé).
    expect(getProfilesMock).not.toHaveBeenCalled();
    expect(getOffersMock).toHaveBeenCalledWith(
      expect.objectContaining({ archived: false }),
    );
  });

  it("affiche la liste des offres archivées (mode archivé)", async () => {
    getProfilesMock.mockResolvedValue([profile]);
    getOffersMock.mockResolvedValue({
      ...offersResponse,
      items: [{ ...offer, archived: true }],
    });
    renderBrowser({ archived: true });

    expect(await screen.findByText("Développeur Python")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Offres archivées" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Désarchiver/ }),
    ).toBeInTheDocument();
    expect(getOffersMock).toHaveBeenCalledWith(
      expect.objectContaining({ archived: true }),
    );
  });

  it("archive les offres sélectionnées en masse", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    archiveOfferMock.mockResolvedValue({});
    renderBrowser({ archived: false });

    await screen.findByText("Développeur Python");
    await user.click(
      screen.getByRole("checkbox", { name: "Sélectionner Développeur Python" }),
    );
    await user.click(screen.getByRole("button", { name: /Archiver/ }));

    await waitFor(() =>
      expect(archiveOfferMock).toHaveBeenCalledWith(7, true),
    );
  });

  it("désarchive les offres sélectionnées en masse", async () => {
    const user = userEvent.setup();
    getProfilesMock.mockResolvedValue([profile]);
    getOffersMock.mockResolvedValue({
      ...offersResponse,
      items: [{ ...offer, archived: true }],
    });
    archiveOfferMock.mockResolvedValue({});
    renderBrowser({ archived: true });

    await screen.findByText("Développeur Python");
    await user.click(
      screen.getByRole("checkbox", { name: "Sélectionner Développeur Python" }),
    );
    await user.click(screen.getByRole("button", { name: /Désarchiver/ }));

    await waitFor(() =>
      expect(archiveOfferMock).toHaveBeenCalledWith(7, false),
    );
  });

  it("filtre par source (fetch débouncé avec le paramètre source)", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    renderBrowser({ archived: false });

    await screen.findByText("Développeur Python");
    await user.type(screen.getByPlaceholderText("Source"), "hellowork");
    await waitFor(() =>
      expect(getOffersMock).toHaveBeenCalledWith(
        expect.objectContaining({ source: "hellowork" }),
      ),
    );
  });

  it("efface le filtre source via le bouton ✕", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    renderBrowser({ archived: false });

    await screen.findByText("Développeur Python");
    await user.type(screen.getByPlaceholderText("Source"), "hellowork");
    await waitFor(() =>
      expect(getOffersMock).toHaveBeenCalledWith(
        expect.objectContaining({ source: "hellowork" }),
      ),
    );
    await user.click(
      screen.getByRole("button", { name: "Effacer le filtre source" }),
    );
    // Une fois le filtre vidé, le dernier fetch ne filtre plus par source
    // (l'objet porte `source: undefined`, jamais transmis au query string).
    await waitFor(() => {
      const calls = getOffersMock.mock.calls;
      const last = calls[calls.length - 1];
      expect(last?.[0]?.source).toBeUndefined();
    });
  });

  it("affiche « Ajouter des offres d'emploi » sur les actives, jamais sur les archivées", async () => {
    getOffersMock.mockResolvedValue(offersResponse);
    const { unmount } = renderBrowser({ archived: false });
    expect(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    ).toBeInTheDocument();
    unmount();

    getProfilesMock.mockResolvedValue([profile]);
    getOffersMock.mockResolvedValue({
      ...offersResponse,
      items: [{ ...offer, archived: true }],
    });
    renderBrowser({ archived: true });
    await screen.findByText("Développeur Python");
    expect(
      screen.queryByRole("button", { name: "Ajouter des offres d'emploi" }),
    ).not.toBeInTheDocument();
  });

  it("affiche le bouton d'ajout même quand la liste est vide", async () => {
    getOffersMock.mockResolvedValue({ ...offersResponse, total: 0, items: [] });
    renderBrowser({ archived: false });

    expect(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    ).toBeInTheDocument();
    // Liste vide : pas de bouton Archiver, mais le bouton d'ajout reste visible.
    expect(screen.queryByRole("button", { name: /Archiver/ })).not.toBeInTheDocument();
  });

  it("ouvre la modale d'ajout au clic", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    renderBrowser();

    await user.click(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    );

    expect(screen.getByLabelText("URL de l'offre")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Valider" })).toBeInTheDocument();
  });

  it("valide l'URL saisie et déclenche l'ingestion avec max_offers par défaut (5)", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    addOfferFromUrlMock.mockResolvedValue(addResult);
    renderBrowser();

    await user.click(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    );
    await user.type(
      screen.getByLabelText("URL de l'offre"),
      "https://example.com/offre/123",
    );
    await user.click(screen.getByRole("button", { name: "Valider" }));

    // Le slider est à sa valeur par défaut (5) : la mutation transmet l'URL et
    // `max_offers` (défaut du composant, pas de valeur 0 possible), sans
    // `source` (champ optionnel vide → undefined, fetch de la page côté serveur).
    await waitFor(() =>
      expect(addOfferFromUrlMock).toHaveBeenCalledWith(
        "https://example.com/offre/123",
        5,
        undefined,
      ),
    );
  });

  it("affiche l'erreur et garde la modale ouverte en cas d'échec", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    addOfferFromUrlMock.mockRejectedValue(
      new Error("Cette offre est déjà en base (id=12)"),
    );
    renderBrowser();

    await user.click(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    );
    await user.type(
      screen.getByLabelText("URL de l'offre"),
      "https://example.com/offre/123",
    );
    await user.click(screen.getByRole("button", { name: "Valider" }));

    // L'erreur serveur (detail) est affichée et la modale reste ouverte.
    expect(
      await screen.findByText("Cette offre est déjà en base (id=12)"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("URL de l'offre")).toBeInTheDocument();
  });

  it("affiche l'écran de chargement et verrouille la modale pendant l'ingestion", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    // Ingestion laissée « en cours » (promesse non résolue) pour observer
    // l'écran de chargement pendant `isPending`.
    let resolveAdd!: (value: AddOffersResult) => void;
    addOfferFromUrlMock.mockReturnValue(
      new Promise<AddOffersResult>((resolve) => {
        resolveAdd = resolve;
      }),
    );
    renderBrowser();

    await user.click(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    );
    await user.type(
      screen.getByLabelText("URL de l'offre"),
      "https://example.com/offre/123",
    );
    await user.click(screen.getByRole("button", { name: "Valider" }));

    // Le formulaire est remplacé par l'écran de chargement.
    expect(
      await screen.findByText(
        "Récupération de la page et extraction des offres en cours…",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("URL de l'offre")).not.toBeInTheDocument();

    // Modale verrouillée : Escape ne la ferme pas pendant l'envoi.
    await user.keyboard("{Escape}");
    expect(
      screen.getByText(
        "Récupération de la page et extraction des offres en cours…",
      ),
    ).toBeInTheDocument();

    // À la fin de l'ingestion, l'écran de succès remplace le chargement (la
    // modale ne se ferme pas automatiquement : le résumé doit être lisible).
    resolveAdd!(addResult);
    expect(
      await screen.findByText("1 offre ajoutée"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Récupération de la page et extraction des offres en cours…",
      ),
    ).not.toBeInTheDocument();
  });

  it("affiche le slider « nombre maximal d'offres » avec la valeur par défaut 5", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    renderBrowser();

    await user.click(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    );

    const slider = screen.getByRole("slider", {
      name: "Nombre maximal d'offres : 5",
    });
    expect(slider).toBeInTheDocument();
    // Bornes alignées sur le contrat API (1 → 20), valeur par défaut 5.
    expect(slider).toHaveAttribute("min", "1");
    expect(slider).toHaveAttribute("max", "20");
    expect(slider).toHaveValue("5");
  });

  it("transmet la valeur choisie du slider à l'ingestion", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    addOfferFromUrlMock.mockResolvedValue(addResult);
    renderBrowser();

    await user.click(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    );
    await user.type(
      screen.getByLabelText("URL de l'offre"),
      "https://example.com/offre/123",
    );

    // Déplacement du slider vers 12 : le libellé se met à jour.
    const slider = screen.getByRole("slider", {
      name: "Nombre maximal d'offres : 5",
    });
    fireEvent.change(slider, { target: { value: "12" } });
    expect(
      screen.getByRole("slider", { name: "Nombre maximal d'offres : 12" }),
    ).toHaveValue("12");

    await user.click(screen.getByRole("button", { name: "Valider" }));
    await waitFor(() =>
      expect(addOfferFromUrlMock).toHaveBeenCalledWith(
        "https://example.com/offre/123",
        12,
        undefined,
      ),
    );
  });

  it("affiche le résumé d'ingestion avec les offres déjà présentes en base", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    addOfferFromUrlMock.mockResolvedValue(addResultList);
    renderBrowser();

    await user.click(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    );
    await user.type(
      screen.getByLabelText("URL de l'offre"),
      "https://example.com/liste",
    );
    await user.click(screen.getByRole("button", { name: "Valider" }));

    // Résumé : ajoutée + déjà présente. La modale reste ouverte (pas de
    // fermeture automatique) pour laisser lire le compte. Le bouton de fermeture
    // visible est ciblé par son texte (le ✕ du header porte aussi aria-label
    // « Fermer »).
    expect(await screen.findByText("1 offre ajoutée")).toBeInTheDocument();
    expect(
      screen.getByText("1 déjà présente en base"),
    ).toBeInTheDocument();
    expect(screen.getByText("Fermer")).toBeInTheDocument();
  });

  it("garde la modale ouverte après succès puis la ferme via « Fermer »", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    addOfferFromUrlMock.mockResolvedValue(addResult);
    renderBrowser();

    await user.click(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    );
    await user.type(
      screen.getByLabelText("URL de l'offre"),
      "https://example.com/offre/123",
    );
    await user.click(screen.getByRole("button", { name: "Valider" }));

    // Succès : la modale reste ouverte (écran de résumé), pas de fermeture
    // automatique.
    expect(await screen.findByText("1 offre ajoutée")).toBeInTheDocument();

    // « Fermer » (texte visible, pas le ✕ du header) réinitialise le formulaire
    // et referme la modale.
    await user.click(screen.getByText("Fermer"));
    await waitFor(() =>
      expect(screen.queryByLabelText("URL de l'offre")).not.toBeInTheDocument(),
    );
  });

  it("n'exige pas de contenu collé : l'URL seule active la validation", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    renderBrowser();

    await user.click(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    );

    // Désactivé tant que l'URL est vide (le contenu collé est optionnel).
    const submit = screen.getByRole("button", { name: "Valider" });
    expect(submit).toBeDisabled();

    // L'URL seule suffit : sans contenu collé, l'URL est récupérée par fetch.
    await user.type(
      screen.getByLabelText("URL de l'offre"),
      "https://example.com/offre/123",
    );
    expect(submit).toBeEnabled();
  });

  it("transmet le contenu collé (champ « Contenu de la page ») à l'ingestion", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    addOfferFromUrlMock.mockResolvedValue(addResult);
    renderBrowser();

    await user.click(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    );
    await user.type(
      screen.getByLabelText("URL de l'offre"),
      "https://example.com/offre/123",
    );
    await user.type(
      screen.getByLabelText("Contenu de la page (optionnel)"),
      "Data Engineer chez Acme - Python SQL",
    );
    await user.click(screen.getByRole("button", { name: "Valider" }));

    // Le contenu collé est transmis tel quel : il remplace le fetch de la page
    // côté serveur (l'URL n'est jamais récupérée).
    await waitFor(() =>
      expect(addOfferFromUrlMock).toHaveBeenCalledWith(
        "https://example.com/offre/123",
        5,
        "Data Engineer chez Acme - Python SQL",
      ),
    );
  });

  it("désactive le slider quand un contenu est collé (offre unique)", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    renderBrowser();

    await user.click(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    );

    const slider = screen.getByRole("slider", {
      name: "Nombre maximal d'offres : 5",
    });
    expect(slider).toBeEnabled();

    // Un contenu collé = offre unique : le nombre d'offres d'une liste n'a plus
    // de sens, le slider est désactivé et le texte d'aide l'explique.
    await user.type(
      screen.getByLabelText("Contenu de la page (optionnel)"),
      "contenu",
    );
    expect(
      screen.getByRole("slider", { name: "Nombre maximal d'offres : 5" }),
    ).toBeDisabled();
    expect(
      screen.getByText(
        "Offre unique : le contenu collé remplace la récupération automatique de la page.",
      ),
    ).toBeInTheDocument();
  });

  it("affiche l'erreur de l'ingestion par contenu collé et garde la modale ouverte", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    addOfferFromUrlMock.mockRejectedValue(
      new Error("Cette offre est déjà en base (id=12)"),
    );
    renderBrowser();

    await user.click(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    );
    await user.type(
      screen.getByLabelText("URL de l'offre"),
      "https://example.com/offre/123",
    );
    await user.type(
      screen.getByLabelText("Contenu de la page (optionnel)"),
      "contenu",
    );
    await user.click(screen.getByRole("button", { name: "Valider" }));

    // L'erreur serveur (detail) est affichée et la modale reste ouverte, le
    // contenu collé toujours présent.
    expect(
      await screen.findByText("Cette offre est déjà en base (id=12)"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Contenu de la page (optionnel)"),
    ).toBeInTheDocument();
  });

  it("réinitialise le formulaire (URL, slider, contenu) après un ajout avec contenu collé", async () => {
    const user = userEvent.setup();
    getOffersMock.mockResolvedValue(offersResponse);
    addOfferFromUrlMock.mockResolvedValue(addResult);
    renderBrowser();

    await user.click(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    );
    await user.type(
      screen.getByLabelText("URL de l'offre"),
      "https://example.com/offre/123",
    );
    await user.type(
      screen.getByLabelText("Contenu de la page (optionnel)"),
      "contenu",
    );
    await user.click(screen.getByRole("button", { name: "Valider" }));
    expect(await screen.findByText("1 offre ajoutée")).toBeInTheDocument();
    await user.click(screen.getByText("Fermer"));

    // Réouverture : formulaire vide, slider de nouveau actif (défaut 5).
    await user.click(
      await screen.findByRole("button", { name: "Ajouter des offres d'emploi" }),
    );
    expect(screen.getByLabelText("URL de l'offre")).toHaveValue("");
    expect(screen.getByLabelText("Contenu de la page (optionnel)")).toHaveValue("");
    expect(
      screen.getByRole("slider", { name: "Nombre maximal d'offres : 5" }),
    ).toBeEnabled();
  });
});
