import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  Badge,
  Button,
  Modal,
  ScoreBar,
  ScoreBreakdown,
  ScorePill,
  scoreBadgeClass,
  scoreTone,
} from "@/components/ui";

describe("Button", () => {
  it("rend un <button> et déclenche onClick", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Valider</Button>);
    const btn = screen.getByRole("button", { name: "Valider" });
    await user.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("rend un bouton désactivé quand disabled", () => {
    render(<Button disabled>Valider</Button>);
    expect(screen.getByRole("button", { name: "Valider" })).toBeDisabled();
  });

  it("rend un <a> avec href quand href est fourni", () => {
    render(
      <Button href="/api/v1/cvs/1/pdf" download>
        Télécharger
      </Button>,
    );
    const link = screen.getByRole("link", { name: "Télécharger" });
    expect(link).toHaveAttribute("href", "/api/v1/cvs/1/pdf");
  });
});

describe("ScorePill", () => {
  it("affiche un tiret pour un score null", () => {
    render(<ScorePill score={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("arrondit le score affiché", () => {
    render(<ScorePill score={84.6} />);
    expect(screen.getByText("85")).toBeInTheDocument();
  });

  it("affiche un score nul", () => {
    render(<ScorePill score={0} />);
    expect(screen.getByText("0")).toBeInTheDocument();
  });
});

describe("scoreTone / scoreBadgeClass", () => {
  it("tierce les scores par seuils (≥80 vert, ≥60 bleu, ≥40 ambre, sinon rouge)", () => {
    expect(scoreTone(95)).toBe("emerald");
    expect(scoreTone(80)).toBe("emerald");
    expect(scoreTone(70)).toBe("sky");
    expect(scoreTone(50)).toBe("amber");
    expect(scoreTone(10)).toBe("red");
  });

  it("retourne des classes de badge cohérentes avec le tone", () => {
    expect(scoreBadgeClass(95)).toContain("emerald");
    expect(scoreBadgeClass(10)).toContain("red");
  });
});

describe("ScoreBar", () => {
  it("borne la largeur affichée à 100 %", () => {
    render(<ScoreBar label="Compétences" value={1.5} />);
    expect(screen.getByText("100")).toBeInTheDocument();
  });

  it("affiche le pourcentage arrondi", () => {
    render(<ScoreBar label="Compétences" value={0.85} />);
    expect(screen.getByText("85")).toBeInTheDocument();
  });
});

describe("ScoreBreakdown", () => {
  it("libelle les sous-scores connus", () => {
    render(
      <ScoreBreakdown breakdown={{ title_score: 0.9, skills_score: 0.5 }} />,
    );
    expect(screen.getByText("Intitulé")).toBeInTheDocument();
    expect(screen.getByText("Compétences")).toBeInTheDocument();
  });
});

describe("Badge", () => {
  it("applique la classe du tone", () => {
    render(<Badge tone="green">Actif</Badge>);
    expect(screen.getByText("Actif")).toHaveClass("bg-emerald-100");
  });
});

describe("Modal", () => {
  it("rend rien quand fermé", () => {
    render(
      <Modal open={false} onClose={vi.fn()}>
        Contenu
      </Modal>,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("affiche le titre et le contenu quand ouvert", () => {
    render(
      <Modal open title="Aperçu" onClose={vi.fn()}>
        Contenu
      </Modal>,
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Aperçu")).toBeInTheDocument();
    expect(screen.getByText("Contenu")).toBeInTheDocument();
  });

  it("ferme sur la touche Échap", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose}>
        Contenu
      </Modal>,
    );
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ferme au clic sur le fond, pas au clic dans le contenu", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose}>
        Contenu
      </Modal>,
    );
    await user.click(screen.getByText("Contenu"));
    expect(onClose).not.toHaveBeenCalled();
    await user.click(document.querySelector(".fixed.inset-0") as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("met le focus sur la boîte de dialogue à l'ouverture", () => {
    render(
      <Modal open onClose={vi.fn()}>
        Contenu
      </Modal>,
    );
    expect(screen.getByRole("dialog")).toHaveFocus();
  });

  it("piège le focus : Tab/Shift+Tab cyclent parmi les éléments du dialog", () => {
    render(
      <Modal open onClose={vi.fn()}>
        <button>A</button>
        <button>B</button>
      </Modal>,
    );
    // Ordre DOM des éléments focusables du dialog : le bouton « Fermer » de
    // l'en-tête (premier), puis les enfants A, B (dernier).
    const close = screen.getByRole("button", { name: "Fermer" });
    const b = screen.getByRole("button", { name: "B" });

    // Tab depuis le dernier élément focusable → retour au premier.
    b.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(close).toHaveFocus();

    // Shift+Tab depuis le premier élément focusable → retour au dernier.
    close.focus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(b).toHaveFocus();
  });

  it("restaure le focus sur l'élément déclencheur à la fermeture", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>Ouvrir</button>
          <Modal open={open} onClose={() => setOpen(false)}>
            Contenu
          </Modal>
        </>
      );
    }
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Ouvrir" });
    await user.click(trigger);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
