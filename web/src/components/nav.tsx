"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useArchivedDetail } from "@/components/archived-detail-context";

const LINKS = [
  { href: "/offers", label: "Offres" },
  { href: "/offers/archived", label: "Offres archivées" },
  { href: "/profiles", label: "Profils" },
  { href: "/search-settings", label: "Recherches sauvegardées" },
];

// « Offres » reste actif sur tous les sous-chemins sauf /offers/archived
// (réservé au lien dédié). Les autres liens sont actifs sur leur sous-arbre.
function isLinkActive(pathname: string, link: (typeof LINKS)[number]) {
  if (link.href === "/offers") {
    return (
      pathname === "/offers" ||
      (pathname.startsWith("/offers/") && !pathname.startsWith("/offers/archived"))
    );
  }
  return pathname === link.href || pathname.startsWith(`${link.href}/`);
}

export function Nav() {
  const pathname = usePathname();
  const { archived } = useArchivedDetail();
  // Détail d'une offre archivée (chemin /offers/[id] à lui seul) : seul le lien
  // « Offres archivées » est actif.
  const archivedDetail = archived && /^\/offers\/\d+$/.test(pathname);
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-zinc-200 bg-white">
      <div className="px-4 py-4 text-sm font-semibold tracking-tight text-zinc-900">
        job_copilot
      </div>
      <nav className="flex flex-col gap-1 px-2 pb-4">
        {LINKS.map((link) => {
          const active = archivedDetail
            ? link.href === "/offers/archived"
            : isLinkActive(pathname, link);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`rounded-md px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-zinc-900 text-white"
                  : "text-zinc-600 hover:bg-zinc-100"
              }`}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
