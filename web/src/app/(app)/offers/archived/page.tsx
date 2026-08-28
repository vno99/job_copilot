import { OffersBrowser } from "@/components/offers-browser";

// Page « Offres archivées » — navigateur partagé, mode archivé (désarchivage
// en masse, profil actif par défaut pour le détail).
export default function ArchivedOffersPage() {
  return <OffersBrowser archived />;
}
