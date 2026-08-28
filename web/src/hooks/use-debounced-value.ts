"use client";

import { useEffect, useState } from "react";

// Retarde la propagation d'une valeur changeant fréquemment (ex. saisie dans un
// champ de recherche) : l'état retourné ne se met à jour qu'après `delay` ms
// sans changement. Utilisé par le filtre entreprise pour ne déclencher un fetch
// react-query qu'à la fin de la saisie.
export function useDebouncedValue<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}
