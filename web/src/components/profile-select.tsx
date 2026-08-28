"use client";

import { useEffect, useId, useRef, useState } from "react";
import {
  ApplicationSubmittedIcon,
  CvGeneratedIcon,
  LetterGeneratedIcon,
  ScorePill,
} from "@/components/ui";

export interface ProfileOption {
  id: number;
  label: string;
  isActive?: boolean;
  score?: number | null;
  // Indicateurs de documents générés pour le couple (offre, profil), affichés
  // à côté du score comme dans la liste des offres (non cliquables).
  hasCv?: boolean;
  hasLetter?: boolean;
  // Suivi « candidature envoyée » pour le couple (coche verte après la lettre).
  applicationSubmitted?: boolean;
}

// Menu déroulant « Profil candidat » du détail d'une offre. Remplace le <select>
// natif pour afficher, à côté de chaque profil, son score sous forme de badge
// coloré (ScorePill) quand il existe. Fermeture : clic extérieur, touche Échap,
// ou sélection d'un profil.
export function ProfileSelect({
  options,
  value,
  onChange,
  disabled,
  label = "Profil candidat",
}: {
  options: ProfileOption[];
  value: number | null;
  onChange: (id: number | null) => void;
  disabled?: boolean;
  label?: string;
}) {
  const rootId = useId();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const selected = options.find((o) => o.id === value);

  return (
    <div>
      {label && (
        <label
          htmlFor={rootId}
          className="block text-xs font-medium text-zinc-500"
        >
          {label}
        </label>
      )}
      <div ref={rootRef} className="relative">
        <button
          type="button"
          id={rootId}
          onClick={() => setOpen((o) => !o)}
          disabled={disabled || options.length === 0}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-disabled={disabled || options.length === 0}
          className="mt-1 flex w-full items-center justify-between gap-2 rounded-md border border-zinc-300 px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span className="truncate text-zinc-900">
            {selected?.label ?? "Aucun profil candidat"}
          </span>
          <svg
            viewBox="0 0 20 20"
            className="h-4 w-4 shrink-0 text-zinc-400"
            aria-hidden="true"
          >
            <path
              d="M5 8l5 5 5-5"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>

        {open && (
          <ul
            role="listbox"
            className="absolute z-10 mt-1 max-h-64 w-full overflow-auto rounded-md border border-zinc-300 bg-white py-1 shadow-lg"
          >
            {options.map((opt) => (
              <li key={opt.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={opt.id === value}
                  onClick={() => {
                    onChange(opt.id);
                    setOpen(false);
                  }}
                  className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-sm hover:bg-zinc-50"
                >
                  <span className="truncate text-zinc-900">
                    {opt.label}
                    {opt.isActive ? (
                      <span className="text-zinc-400"> (actif)</span>
                    ) : null}
                  </span>
                  <span className="inline-flex shrink-0 items-center gap-1">
                    {opt.score != null && <ScorePill score={opt.score} />}
                    {opt.hasCv && <CvGeneratedIcon />}
                    {opt.hasLetter && <LetterGeneratedIcon />}
                    {opt.applicationSubmitted && <ApplicationSubmittedIcon />}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
