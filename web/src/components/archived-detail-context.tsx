"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

// Signale à la navigation que le détail d'offre affiché est celui d'une offre
// archivée : le chemin /offers/[id] ne l'indique pas, or le menu de gauche doit
// alors mettre en avant « Offres archivées ». Mis à jour par la page de détail
// dès que l'état d'archivage est connu.
const ArchivedDetailContext = createContext<{
  archived: boolean;
  setArchived: (value: boolean) => void;
}>({ archived: false, setArchived: () => {} });

export function ArchivedDetailProvider({ children }: { children: ReactNode }) {
  const [archived, setArchived] = useState(false);
  return (
    <ArchivedDetailContext.Provider value={{ archived, setArchived }}>
      {children}
    </ArchivedDetailContext.Provider>
  );
}

export function useArchivedDetail() {
  return useContext(ArchivedDetailContext);
}
