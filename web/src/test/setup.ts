// Configuration partagée des tests unitaires (vitest + jsdom).
// Étend les matchers de vitest avec les assertions DOM de jest-dom
// (toBeInTheDocument, toBeDisabled, toHaveAttribute, …).
import "@testing-library/jest-dom/vitest";
// Nettoyage du DOM entre chaque test (les globals vitest ne sont pas activés,
// RTL ne détecte donc pas `afterEach` tout seul).
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => cleanup());
