"use client";

import { useEffect, useRef } from "react";
import type { ReactNode, Ref } from "react";

export function Button({
  children,
  onClick,
  disabled,
  variant = "primary",
  className = "",
  type = "button",
  title,
  href,
  download,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "secondary" | "danger" | "success" | "ghost";
  className?: string;
  type?: "button" | "submit";
  title?: string;
  // Si présent, rend un lien `<a>` (mêmes styles) au lieu d'un `<button>` —
  // ex. téléchargement d'un fichier servi par l'API.
  href?: string;
  download?: boolean;
}) {
  const styles = {
    primary:
      "bg-zinc-900 text-white hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50",
    secondary:
      "bg-white text-zinc-900 border border-zinc-300 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50",
    danger:
      "bg-red-600 text-white hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-50",
    success:
      "bg-emerald-600 text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50",
    ghost: "text-zinc-600 hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50",
  }[variant];
  const classes = `inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${styles} ${className}`;
  if (href) {
    return (
      <a href={href} download={download} title={title} className={classes}>
        {children}
      </a>
    );
  }
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      title={title}
      className={classes}
    >
      {children}
    </button>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "green" | "red" | "amber" | "neutral" | "blue";
}) {
  const tones = {
    green: "bg-emerald-100 text-emerald-800",
    red: "bg-red-100 text-red-800",
    amber: "bg-amber-100 text-amber-800",
    blue: "bg-sky-100 text-sky-800",
    neutral: "bg-zinc-100 text-zinc-700",
  }[tone];
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${tones}`}
    >
      {children}
    </span>
  );
}

export function Card({
  children,
  className = "",
  ref,
}: {
  children: ReactNode;
  className?: string;
  ref?: Ref<HTMLDivElement>;
}) {
  return (
    <div
      ref={ref}
      className={`rounded-lg border border-zinc-200 bg-white ${className}`}
    >
      {children}
    </div>
  );
}

export function Spinner() {
  return (
    <div className="py-10 text-center text-sm text-zinc-500">Chargement…</div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {message}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="py-10 text-center text-sm text-zinc-500">{children}</div>;
}

// Barre de score normalisée (valeur 0..1 → pourcentage).
export function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div className="flex items-center gap-3">
      <span className="w-36 shrink-0 text-xs text-zinc-500">{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-zinc-100">
        <div
          className="h-full rounded-full bg-emerald-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-10 shrink-0 text-right text-xs tabular-nums text-zinc-600">
        {pct}
      </span>
    </div>
  );
}

// Seuls les sous-scores réellement produits par le matching sont libellés
// (`location_score` / `contract_score` n'existent plus).
const BREAKDOWN_LABELS: Record<string, string> = {
  title_score: "Intitulé",
  skills_score: "Compétences",
  experience_score: "Expérience",
  education_score: "Formation",
};

export function ScoreBreakdown({ breakdown }: { breakdown: Record<string, number> }) {
  return (
    <div className="space-y-2">
      {Object.entries(breakdown).map(([key, value]) => (
        <ScoreBar key={key} label={BREAKDOWN_LABELS[key] ?? key} value={Number(value)} />
      ))}
    </div>
  );
}

// Teinte d'un score, partagée entre le badge du tableau (ScorePill) et les
// affichages du détail : ≥80 vert, ≥60 bleu, ≥40 ambre, sinon rouge.
export function scoreTone(score: number): "emerald" | "sky" | "amber" | "red" {
  if (score >= 80) return "emerald";
  if (score >= 60) return "sky";
  if (score >= 40) return "amber";
  return "red";
}

// Classes d'un badge de score (fond pastel + texte), alignées sur ScorePill :
// utilisées par le tableau ET par les affichages du détail.
export function scoreBadgeClass(score: number): string {
  const badges: Record<"emerald" | "sky" | "amber" | "red", string> = {
    emerald: "bg-emerald-100 text-emerald-800",
    sky: "bg-sky-100 text-sky-800",
    amber: "bg-amber-100 text-amber-800",
    red: "bg-red-100 text-red-800",
  };
  return badges[scoreTone(score)];
}

export function ScorePill({
  score,
  title,
}: {
  score: number | null;
  title?: string;
}) {
  if (score === null) return <span className="text-zinc-400">—</span>;
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold tabular-nums ${scoreBadgeClass(score)}`}
    >
      {Math.round(score)}
    </span>
  );
}

// Icône d'indicateur « CV généré » (non cliquable) : un cv_version existe pour
// le couple (offre, profil). Simple indicateur, seul le score est cliquable.
export function CvGeneratedIcon() {
  return (
    // Tooltip sur le span (le prop `title` n'existe pas sur les props SVG).
    <span title="CV généré">
      <svg
        role="img"
        aria-label="CV généré"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="h-3.5 w-3.5 shrink-0 text-zinc-500"
      >
        <path d="M5 1.5h5l3 3v9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-11a1 1 0 0 1 1-1z" />
        <path d="M10 1.5V5h3" />
        <path d="M6 8h4M6 10.5h4" />
      </svg>
    </span>
  );
}

// Icône d'indicateur « Lettre de motivation générée » (non cliquable) : une
// letter_version existe pour le couple (offre, profil).
export function LetterGeneratedIcon() {
  return (
    <span title="Lettre de motivation générée">
      <svg
        role="img"
        aria-label="Lettre de motivation générée"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="h-3.5 w-3.5 shrink-0 text-zinc-500"
      >
        <rect x="1.5" y="3.5" width="13" height="9" rx="1" />
        <path d="M2.5 5.5l5.5 3.5 5.5-3.5" />
      </svg>
    </span>
  );
}

// Icône d'indicateur « Candidature envoyée » (non cliquable) : une coche verte,
// affichée après le score du profil une fois la candidature déposée pour le
// couple (offre, profil) — voir ``cv_version.application_submitted``.
export function ApplicationSubmittedIcon() {
  return (
    <span title="Candidature envoyée">
      <svg
        role="img"
        aria-label="Candidature envoyée"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="h-3.5 w-3.5 shrink-0 text-emerald-600"
      >
        <path d="M3.5 8.5l3 3 6-6.5" />
      </svg>
    </span>
  );
}

// Fenêtre modale (aperçu CV, édition, confirmation). Fermeture : clic sur le
// fond, bouton ✕ ou touche Escape.
export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  // onClose stabilisé dans une ref : l'effet de focus ne dépend alors que de
  // `open` (un re-render parent relancerait sinon l'effet et ferait perdre le
  // focus pendant que la modale est ouverte).
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    // Ne focaliser le conteneur que si aucun champ n'a déjà reçu le focus
    // (autoFocus) : sans cette garde, cet effet (post-commit) écrase le focus
    // auto des champs URL/Titre. Le focus reste dans la modale → trap de Tab OK.
    if (!dialogRef.current?.contains(document.activeElement)) {
      dialogRef.current?.focus();
    }

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onCloseRef.current();
        return;
      }
      // Focus trap : Tab / Shift+Tab cyclent parmi les éléments focusables du
      // dialog (le focus ne sort jamais de la modale).
      if (e.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusables = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      // Restauration du focus sur l'élément déclencheur à la fermeture.
      previouslyFocused?.focus();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3">
          <div className="text-sm font-semibold text-zinc-900">{title}</div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fermer"
            className="rounded-md px-2 py-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
          >
            ✕
          </button>
        </div>
        <div className="overflow-auto px-4 py-4">{children}</div>
      </div>
    </div>
  );
}
