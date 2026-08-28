import { describe, expect, it } from "vitest";
import { formatDate, formatDateTime } from "@/lib/datetime";

describe("formatDateTime", () => {
  it("formate une date/heure ISO en « JJ/MM/AAAA à HH:MM »", () => {
    // Date construite en heure locale puis sérialisée : l'aller-retour
    // toISOString → new Date restitue le même instant, quel que soit le fuseau
    // de la machine qui exécute les tests.
    const iso = new Date(2026, 7, 1, 12, 30).toISOString();
    expect(formatDateTime(iso)).toBe("01/08/2026 à 12:30");
  });

  it("retourne une chaîne vide pour une valeur nulle ou vide", () => {
    expect(formatDateTime(null)).toBe("");
    expect(formatDateTime("")).toBe("");
  });
});

describe("formatDate", () => {
  it("formate une date « YYYY-MM-DD » en « JJ/MM/AAAA »", () => {
    expect(formatDate("2026-07-01")).toBe("01/07/2026");
    // Parsée par composants : pas de décalage de fuseau (new Date("YYYY-MM-DD")
    // interprète minuit UTC et peut reculer d'un jour dans les fuseaux négatifs).
    expect(formatDate("2026-01-01")).toBe("01/01/2026");
  });

  it("ignore la partie horaire d'une date/heure ISO", () => {
    expect(formatDate("2026-07-01T10:00:00Z")).toBe("01/07/2026");
  });

  it("retourne une chaîne vide pour une valeur nulle, vide ou illisible", () => {
    expect(formatDate(null)).toBe("");
    expect(formatDate(undefined)).toBe("");
    expect(formatDate("")).toBe("");
    expect(formatDate("01/07/2026")).toBe("");
  });
});
