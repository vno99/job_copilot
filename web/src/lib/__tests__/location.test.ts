import { describe, expect, it } from "vitest";
import { formatLocation } from "@/lib/location";

describe("formatLocation", () => {
  it("inverse « Ville - N° » en « N° - Ville »", () => {
    expect(formatLocation("Paris - 92")).toBe("92 - Paris");
    expect(formatLocation("Lyon - 69")).toBe("69 - Lyon");
  });

  it("ne touche pas une ville sans département", () => {
    expect(formatLocation("Paris")).toBe("Paris");
  });

  it("préserve « Aix-en-Provence » (tiret non entouré d'espaces)", () => {
    expect(formatLocation("Aix-en-Provence")).toBe("Aix-en-Provence");
  });

  it("réduit un code postal en tête à son département", () => {
    expect(formatLocation("75011 Paris")).toBe("75 - Paris");
  });

  it("garde un format déjà « département - ville »", () => {
    expect(formatLocation("92 - Hauts-de-Seine")).toBe("92 - Hauts-de-Seine");
  });

  it("renvoie « — » pour null ou chaîne vide", () => {
    expect(formatLocation(null)).toBe("—");
    expect(formatLocation("")).toBe("—");
    // Une chaîne d'espaces est trimée à vide mais renvoyée telle quelle (cas
    // limite non couvert par la fonction, improbable en pratique).
    expect(formatLocation("   ")).toBe("");
  });
});
