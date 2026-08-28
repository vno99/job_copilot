import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OffersTable } from "@/components/offers-table";
import type { JobOfferListItem, SortField } from "@/lib/api";

// Mocks des modules Next.js : `next/link` (Link rendu en simple <a>) et
// `next/navigation` (useRouter → push espionnable).
const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

// Le vrai Link de Next.js navigue côté client : un <a> natif provoquerait une
// navigation document en jsdom (« Not implemented ») — on la prévient avec
// preventDefault, tout en laissant les handlers du composant s'exécuter.
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

const item: JobOfferListItem = {
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
  scores: [
    {
      candidate_profile_id: 1,
      profile_name: "Profil A",
      total_score: 85,
      created_at: "2026-08-01T10:00:00Z",
      has_cv: true,
      has_letter: false,
      application_submitted: false,
    },
  ],
};

const baseProps = {
  limit: 25,
  offset: 0,
  sort: { field: "ingested_at" as SortField, order: "desc" as const },
  onSort: vi.fn(),
  onOffsetChange: vi.fn(),
  detailHref: (o: JobOfferListItem) => `/offers/${o.id}`,
};

function renderTable(overrides: Partial<typeof baseProps> = {}) {
  const props = { ...baseProps, ...overrides };
  render(
    <OffersTable
      items={[item]}
      total={1}
      {...props}
      onSort={props.onSort}
      onOffsetChange={props.onOffsetChange}
      detailHref={props.detailHref}
    />,
  );
  return props;
}

describe("OffersTable", () => {
  beforeEach(() => {
    pushMock.mockClear();
  });

  it("affiche les valeurs d'une offre (titre, entreprise, localisation, contrat)", () => {
    renderTable();
    expect(screen.getByText("Développeur Python")).toBeInTheDocument();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    // formatLocation inverse « Ville - N° » en « N° - Ville ».
    expect(screen.getByText("75 - Paris")).toBeInTheDocument();
    expect(screen.getByText("CDI")).toBeInTheDocument();
  });

  it("affiche le score sous forme de pill et l'indicateur CV", () => {
    renderTable();
    expect(screen.getByText("85")).toBeInTheDocument();
    expect(screen.getByTitle("CV généré")).toBeInTheDocument();
  });

  it("affiche la coche verte quand la candidature a été envoyée pour le couple", () => {
    const withSubmitted = {
      ...item,
      scores: item.scores.map((s) => ({
        ...s,
        has_letter: true,
        application_submitted: true,
      })),
    };
    render(
      <OffersTable
        items={[withSubmitted]}
        total={1}
        limit={25}
        offset={0}
        sort={baseProps.sort}
        onSort={vi.fn()}
        onOffsetChange={vi.fn()}
        detailHref={(o) => `/offers/${o.id}`}
      />,
    );
    expect(screen.getByTitle("Candidature envoyée")).toBeInTheDocument();
  });

  it("ne rend pas la coche verte tant que la candidature n'est pas envoyée", () => {
    renderTable();
    expect(screen.queryByTitle("Candidature envoyée")).not.toBeInTheDocument();
  });

  it("affiche un tiret dans la cellule score quand l'offre n'a pas de score", () => {
    render(
      <OffersTable
        items={[{ ...item, scores: [] }]}
        total={1}
        limit={25}
        offset={0}
        sort={baseProps.sort}
        onSort={vi.fn()}
        onOffsetChange={vi.fn()}
        detailHref={(o) => `/offers/${o.id}`}
      />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("85")).not.toBeInTheDocument();
  });

  it("navigue au clic sur une ligne", async () => {
    const user = userEvent.setup();
    renderTable();
    await user.click(screen.getByText("Développeur Python"));
    expect(pushMock).toHaveBeenCalledWith("/offers/7");
  });

  it("ne navigue pas au clic sur la pill de score (stopPropagation)", async () => {
    const user = userEvent.setup();
    renderTable();
    await user.click(screen.getByText("85"));
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("trie au clic sur l'en-tête (reset de page + onSort)", async () => {
    const user = userEvent.setup();
    const props = renderTable();
    await user.click(screen.getByRole("button", { name: /Entreprise/ }));
    expect(props.onOffsetChange).toHaveBeenCalledWith(0);
    expect(props.onSort).toHaveBeenCalledWith("company");
  });

  it("affiche la source et trie au clic sur l'en-tête Source", async () => {
    const user = userEvent.setup();
    const props = renderTable();
    expect(screen.getByText("hellowork")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Source/ }));
    expect(props.onOffsetChange).toHaveBeenCalledWith(0);
    expect(props.onSort).toHaveBeenCalledWith("source");
  });

  it("affiche la pagination et déclenche le changement de page", async () => {
    const user = userEvent.setup();
    const onOffsetChange = vi.fn();
    render(
      <OffersTable
        items={[item]}
        total={30}
        limit={25}
        offset={0}
        sort={baseProps.sort}
        onSort={vi.fn()}
        onOffsetChange={onOffsetChange}
        detailHref={(o) => `/offers/${o.id}`}
      />,
    );
    expect(screen.getByText("Page 1 / 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "← Précédent" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Suivant →" }));
    expect(onOffsetChange).toHaveBeenCalledWith(25);
  });

  it("sélectionne une offre via sa case à cocher", async () => {
    const user = userEvent.setup();
    const onToggleSelect = vi.fn();
    render(
      <OffersTable
        items={[item]}
        total={1}
        limit={25}
        offset={0}
        sort={baseProps.sort}
        onSort={vi.fn()}
        onOffsetChange={vi.fn()}
        detailHref={(o) => `/offers/${o.id}`}
        selectable
        selectedIds={[]}
        onToggleSelect={onToggleSelect}
        onToggleSelectPage={vi.fn()}
      />,
    );
    await user.click(
      screen.getByRole("checkbox", { name: "Sélectionner Développeur Python" }),
    );
    expect(onToggleSelect).toHaveBeenCalledWith(7);
  });

  it("expose un caption sr-only quand fourni", () => {
    render(
      <OffersTable
        items={[item]}
        total={1}
        limit={25}
        offset={0}
        sort={baseProps.sort}
        onSort={vi.fn()}
        onOffsetChange={vi.fn()}
        detailHref={(o) => `/offers/${o.id}`}
        caption="Offres"
      />,
    );
    const caption = document.querySelector("caption") as HTMLElement | null;
    expect(caption).not.toBeNull();
    expect(caption?.textContent).toBe("Offres");
    expect(caption).toHaveClass("sr-only");
  });

  it("ne rend pas de caption quand absent", () => {
    renderTable();
    expect(document.querySelector("caption")).toBeNull();
  });

  it("sélectionne toute la page via la case d'en-tête", async () => {
    const user = userEvent.setup();
    const onToggleSelectPage = vi.fn();
    render(
      <OffersTable
        items={[item]}
        total={1}
        limit={25}
        offset={0}
        sort={baseProps.sort}
        onSort={vi.fn()}
        onOffsetChange={vi.fn()}
        detailHref={(o) => `/offers/${o.id}`}
        selectable
        selectedIds={[]}
        onToggleSelect={vi.fn()}
        onToggleSelectPage={onToggleSelectPage}
      />,
    );
    const headerCheckbox = screen.getAllByRole("checkbox")[0];
    await user.click(headerCheckbox);
    expect(onToggleSelectPage).toHaveBeenCalledWith([7], true);
  });
});
