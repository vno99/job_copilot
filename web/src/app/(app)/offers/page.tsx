import { OffersBrowser } from "@/components/offers-browser";

// Page « Offres » (actives) — navigateur partagé, mode actif.
export default function OffersPage() {
  return <OffersBrowser archived={false} />;
}
