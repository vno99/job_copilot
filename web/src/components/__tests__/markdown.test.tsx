import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Markdown } from "@/components/markdown";

// Tableau GFM bien formé (une ligne par rangée) — ce que la pass 2 du CV
// doit produire pour être rendu par remark-gfm.
const TABLE = [
  "| Domaine | Technologies |",
  "|---|---|",
  "| Data Engineering | Python, SQL |",
  "| Cloud & DevOps | AWS S3, Docker |",
].join("\n");

describe("Markdown", () => {
  it("rend un tableau GFM comme un <table> (remark-gfm)", () => {
    render(<Markdown content={TABLE} />);
    expect(document.querySelector("table")).not.toBeNull();
    expect(
      screen.getByRole("columnheader", { name: "Domaine" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Python, SQL" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "AWS S3, Docker" })).toBeInTheDocument();
  });

  it("réchappe le HTML brut (aucun élément injecté rendu)", () => {
    render(<Markdown content={'<img src=x onerror="alert(1)">'} />);
    expect(document.querySelector("img")).toBeNull();
  });

  it("rend les rubriques Markdown usuelles", () => {
    render(<Markdown content={"## Compétences\n- Python\n- SQL"} />);
    expect(
      screen.getByRole("heading", { name: "Compétences", level: 2 }),
    ).toBeInTheDocument();
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.getByText("SQL")).toBeInTheDocument();
  });
});
