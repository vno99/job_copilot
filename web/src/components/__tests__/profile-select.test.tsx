import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProfileSelect } from "@/components/profile-select";

const options = [
  { id: 1, label: "CV Ingénieur", isActive: true, score: 85, hasCv: true },
  { id: 2, label: "CV Data Analyst", score: null, hasLetter: true },
];

describe("ProfileSelect", () => {
  it("affiche un placeholder quand aucun profil n'est sélectionné", () => {
    render(<ProfileSelect options={options} value={null} onChange={vi.fn()} />);
    expect(screen.getByText("Aucun profil candidat")).toBeInTheDocument();
  });

  it("affiche le libellé du profil sélectionné", () => {
    render(<ProfileSelect options={options} value={2} onChange={vi.fn()} />);
    expect(screen.getByText("CV Data Analyst")).toBeInTheDocument();
  });

  it("ouvre la listbox au clic et liste les options", async () => {
    const user = userEvent.setup();
    render(<ProfileSelect options={options} value={null} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /CV Ingénieur/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /CV Data Analyst/ }),
    ).toBeInTheDocument();
  });

  it("sélectionne un profil via onChange puis referme", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ProfileSelect options={options} value={null} onChange={onChange} />);
    await user.click(screen.getByRole("button"));
    await user.click(screen.getByRole("option", { name: /CV Data Analyst/ }));
    expect(onChange).toHaveBeenCalledWith(2);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("affiche le score et les indicateurs de documents générés", async () => {
    const user = userEvent.setup();
    render(<ProfileSelect options={options} value={null} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button"));
    expect(screen.getByText("85")).toBeInTheDocument();
    expect(screen.getByTitle("CV généré")).toBeInTheDocument();
    expect(
      screen.getByTitle("Lettre de motivation générée"),
    ).toBeInTheDocument();
  });

  it("affiche la coche verte quand la candidature a été envoyée", async () => {
    const user = userEvent.setup();
    const withSubmitted = [
      { ...options[0], applicationSubmitted: true },
      ...options.slice(1),
    ];
    render(
      <ProfileSelect options={withSubmitted} value={null} onChange={vi.fn()} />,
    );
    await user.click(screen.getByRole("button"));
    expect(screen.getByTitle("Candidature envoyée")).toBeInTheDocument();
  });

  it("désactive le bouton quand disabled", () => {
    render(
      <ProfileSelect options={options} value={null} onChange={vi.fn()} disabled />,
    );
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("ferme sur la touche Échap", async () => {
    const user = userEvent.setup();
    render(<ProfileSelect options={options} value={null} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("ferme au clic extérieur", async () => {
    const user = userEvent.setup();
    render(<ProfileSelect options={options} value={null} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await user.click(document.body);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
