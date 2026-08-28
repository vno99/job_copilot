"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, use, useRef, useState } from "react";
import type { QueryClient } from "@tanstack/react-query";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { JobOfferDetail } from "@/lib/api";
import { formatDate, formatDateTime } from "@/lib/datetime";
import {
  Badge,
  Button,
  Card,
  ErrorBox,
  Modal,
  ScoreBreakdown,
  Spinner,
  scoreBadgeClass,
} from "@/components/ui";
import { useArchivedDetail } from "@/components/archived-detail-context";
import { ProfileSelect } from "@/components/profile-select";
import { Markdown } from "@/components/markdown";

export default function OfferDetailPage({
  params,
  searchParams,
}: PageProps<"/offers/[id]">) {
  const { id } = use(params);
  // Profil ciblé à l'arrivée via ?candidate_profile_id= (ex. clic sur une ligne
  // ou un score de la liste des offres) ; absent → meilleur score, sinon actif.
  const { candidate_profile_id } = use(searchParams);
  const offerId = Number(id);
  const qc = useQueryClient();
  const router = useRouter();

  const profiles = useQuery({ queryKey: ["profiles"], queryFn: api.getProfiles });

  const initialProfileId = (() => {
    const raw = Array.isArray(candidate_profile_id)
      ? candidate_profile_id[0]
      : candidate_profile_id;
    const n = raw ? Number(raw) : NaN;
    return Number.isFinite(n) ? n : null;
  })();

  // Profil choisi (URL au montage, puis <select>) : null = profil par défaut.
  // L'état ne se met jamais dans un effet.
  const [profileId, setProfileId] = useState<number | null>(initialProfileId);
  const defaultProfileId =
    profiles.data?.find((p) => p.is_active)?.id ??
    profiles.data?.[0]?.id ??
    null;
  const effectiveProfileId =
    profileId !== null && profiles.data?.some((p) => p.id === profileId)
      ? profileId
      : defaultProfileId;

  // Requête de découverte : offre + scores pour le profil courant (URL → actif).
  // Toujours interrogée ; les scores servent de source au menu candidats d'une
  // offre archivée, indépendamment du profil demandé.
  const discovery = useQuery({
    queryKey: ["offer", offerId, effectiveProfileId],
    queryFn: () => api.getOffer(offerId, effectiveProfileId ?? undefined),
    enabled: Number.isFinite(offerId) && !profiles.isLoading,
  });

  // Profil ciblé résolu, dérivé sans effet. Ordre : profil explicitement ciblé
  // (URL depuis le tableau / menu candidats) s'il est valide, sinon le profil au
  // meilleur score, sinon le profil actif. Pour une offre archivée, seuls les
  // profils déjà matchés (o.scores) sont valides ; sans score, null.
  const resolvedProfileId = (() => {
    const d: JobOfferDetail | undefined = discovery.data;
    const isArchived = d?.archived ?? false;
    const scores = d?.scores ?? [];
    const candidateIds = isArchived
      ? scores.map((s) => s.candidate_profile_id)
      : (profiles.data?.map((p) => p.id) ?? []);
    const inCandidates = (pid: number | null) =>
      pid !== null && candidateIds.includes(pid);
    if (inCandidates(profileId)) return profileId;
    // Défaut : le meilleur score (scores triés du plus haut au plus faible),
    // puis le profil actif.
    if (scores.length > 0) return scores[0].candidate_profile_id;
    if (inCandidates(defaultProfileId)) return defaultProfileId;
    if (isArchived) return null;
    return defaultProfileId;
  })();

  const needRefetch = resolvedProfileId !== effectiveProfileId;

  // Détail du profil résolu. Offre active (résolu == profil courant) ou offre
  // archivée atteinte via un profil déjà matché → les données sont déjà dans
  // discovery, la requête est désactivée et affiche son contenu en placeholder.
  // Un second fetch n'est émis que si le profil résolu diffère du profil courant
  // (ex. arrivée sur une offre archivée via un profil qui ne l'a jamais matchée).
  const resolved = useQuery({
    queryKey: ["offer", offerId, resolvedProfileId],
    queryFn: () => api.getOffer(offerId, resolvedProfileId ?? undefined),
    enabled:
      Number.isFinite(offerId) &&
      !profiles.isLoading &&
      needRefetch &&
      resolvedProfileId !== null,
    placeholderData: discovery.data,
  });

  const offer = needRefetch ? resolved : discovery;

  // Offres voisines (boutons + raccourci clavier ←/→) : les cibles sont gelées
  // en chaînes d'URL pour l'effet clavier (react-compiler) ; null si l'offre
  // n'est pas encore chargée ou aux extrémités. La navigation ne cible pas de
  // profil : l'offre d'arrivée choisit son meilleur score, sinon le profil actif.
  const prevHref =
    offer.data?.previous_offer_id != null
      ? `/offers/${offer.data.previous_offer_id}`
      : null;
  const nextHref =
    offer.data?.next_offer_id != null
      ? `/offers/${offer.data.next_offer_id}`
      : null;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null;
      const tag = el?.tagName;
      // Ne pas naviguer pendant qu'une modale est ouverte (le focus y est ou
      // elle est simplement dans le document) ni quand le focus est sur un
      // élément interactif (bouton, champ, contenu éditable) : les flèches
      // sont alors destinées à la modale / au contrôle, pas à la navigation.
      const inDialog = el?.closest('[role="dialog"]') != null;
      const dialogOpen =
        document.querySelector('[role="dialog"]') != null ||
        document.querySelector("dialog[open]") != null;
      if (
        inDialog ||
        dialogOpen ||
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        tag === "SELECT" ||
        tag === "BUTTON" ||
        el?.isContentEditable
      ) {
        return;
      }
      if (e.key === "ArrowLeft" && prevHref) {
        e.preventDefault();
        setProfileId(null);
        router.push(prevHref, { scroll: false });
      } else if (e.key === "ArrowRight" && nextHref) {
        e.preventDefault();
        setProfileId(null);
        router.push(nextHref, { scroll: false });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [prevHref, nextHref, router, setProfileId]);

  const { setArchived } = useArchivedDetail();
  // Met à jour la navigation : le détail d'une offre archivée doit mettre en
  // avant « Offres archivées » (le chemin /offers/[id] seul ne le dit pas).
  useEffect(() => {
    setArchived(offer.data?.archived ?? false);
  }, [offer.data?.archived, setArchived]);

  const cvs = offer.data?.cvs ?? [];
  // Un seul CV par couple (offre, profil) : l'aperçu porte sur le CV du couple.
  const activeCvId = cvs[0]?.id ?? null;

  // Aperçu du CV : ``cv_text`` est le Markdown généré par le LLM, rendu via
  // react-markdown (la route /html a été supprimée). Désactivé tant qu'aucun
  // CV n'est généré pour le couple.
  const activeCv = useQuery({
    queryKey: ["cv", activeCvId],
    queryFn: () => api.getCv(activeCvId ?? 0),
    enabled: activeCvId !== null,
  });

  const letters = offer.data?.letters ?? [];
  // Une seule lettre par couple (offre, profil) : l'aperçu porte sur la lettre
  // du couple.
  const activeLetterId = letters[0]?.id ?? null;

  // Aperçu de la lettre : ``letter_text`` est le Markdown généré par le LLM,
  // rendu via react-markdown. Désactivé tant qu'aucune lettre n'est générée
  // pour le couple.
  const activeLetter = useQuery({
    queryKey: ["letter", activeLetterId],
    queryFn: () => api.getLetter(activeLetterId ?? 0),
    enabled: activeLetterId !== null,
  });

  // Harmonisation des hauteurs : la carte Description s'aligne sur la hauteur
  // de la carte Matching (dynamique), bornée à 24rem au minimum. En CSS pur,
  // un parent à hauteur auto ferait grandir la carte avec tout le texte de la
  // description (plus de scrollbar) ; on mesure donc la carte Matching
  // (ResizeObserver) et on applique sa hauteur à la carte Description — son
  // texte occupe l'espace restant et y défile, la liste des compétences
  // restant épinglée en bas.
  const descCardRef = useRef<HTMLDivElement | null>(null);
  const matchCardRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const matchCard = matchCardRef.current;
    const descCard = descCardRef.current;
    if (!matchCard || !descCard) return;
    const sync = () => {
      // 24rem au minimum ; au-delà, la hauteur de Matching.
      descCard.style.height = `${Math.max(matchCard.offsetHeight, 24 * 16)}px`;
    };
    sync();
    const ro = new ResizeObserver(sync);
    ro.observe(matchCard);
    return () => ro.disconnect();
  });

  // Harmonisation des hauteurs CV/Lettre : quand les deux documents existent,
  // les deux cards prennent la hauteur de la plus grande (24rem au minimum),
  // comme pour Description/Matching. Chaque card défile alors en interne dans
  // l'espace restant.
  const cvCardRef = useRef<HTMLDivElement | null>(null);
  const letterCardRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const cvCard = cvCardRef.current;
    const letterCard = letterCardRef.current;
    if (!cvCard || !letterCard) return;
    const sync = () => {
      const height = Math.max(
        cvCard.offsetHeight,
        letterCard.offsetHeight,
        24 * 16,
      );
      cvCard.style.height = `${height}px`;
      letterCard.style.height = `${height}px`;
    };
    sync();
    const ro = new ResizeObserver(sync);
    ro.observe(cvCard);
    ro.observe(letterCard);
    return () => ro.disconnect();
  });

  const invalidate = (client: QueryClient) => {
    client.invalidateQueries({ queryKey: ["offer", offerId] });
    client.invalidateQueries({ queryKey: ["offers"] });
  };

  const runMatch = useMutation({
    mutationFn: () => api.runMatch(offerId, resolvedProfileId ?? undefined),
    onSuccess: () => invalidate(qc),
  });
  const genCv = useMutation({
    mutationFn: () => api.generateCv(offerId, resolvedProfileId ?? undefined),
    onSuccess: () => invalidate(qc),
  });
  const deleteCv = useMutation({
    mutationFn: () => api.deleteCv(offerId, resolvedProfileId ?? undefined),
    onSuccess: () => invalidate(qc),
  });
  // Bascule du suivi « candidature envoyée » du CV du couple : l'état voulu est
  // l'inverse de l'état affiché (le bouton devient un badge vert, revertible).
  const setSubmitted = useMutation({
    mutationFn: () =>
      api.setCvSubmitted(
        activeCvId ?? 0,
        !(cvs[0]?.application_submitted ?? false),
      ),
    onSuccess: () => invalidate(qc),
  });
  const genLetter = useMutation({
    mutationFn: () => api.generateLetter(offerId, resolvedProfileId ?? undefined),
    onSuccess: () => invalidate(qc),
  });
  const deleteLetter = useMutation({
    mutationFn: () => api.deleteLetter(offerId, resolvedProfileId ?? undefined),
    onSuccess: () => invalidate(qc),
  });
  // Copie de la lettre dans le presse-papiers : retour visuel « Copié ✓ ».
  const [copied, setCopied] = useState(false);
  const copyLetter = async () => {
    const text = activeLetter.data?.letter_text;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* presse-papiers indisponible : on ignore */
    }
  };
  // Suppression en cours de confirmation (modale) : "cv", "letter" ou "match".
  const [confirmDelete, setConfirmDelete] = useState<
    "cv" | "letter" | "match" | null
  >(null);
  const deleteMatch = useMutation({
    mutationFn: () => api.deleteMatch(offerId, resolvedProfileId ?? undefined),
    onSuccess: () => invalidate(qc),
  });
  const archive = useMutation({
    mutationFn: () => api.archiveOffer(offerId, !offer.data?.archived),
    onSuccess: (result) => {
      // Après un archivage, quitter le détail : vers l'offre suivante, sinon
      // retour à la liste des offres non archivées. (Le désarchivage conserve
      // la page courante.)
      const next = offer.data?.next_offer_id ?? null;
      invalidate(qc);
      if (result.archived) {
        if (next != null) {
          setProfileId(null);
          router.push(`/offers/${next}`, { scroll: false });
        } else {
          router.push("/offers", { scroll: false });
        }
      }
    },
  });

  // ``isPlaceholderData`` : les données affichées sont le placeholder de
  // discovery (profil courant), pas encore le détail du profil résolu. Pendant
  // ce fetch (``isFetching``), ne pas rendre un contenu du mauvais profil
  // (CV/lettre/score d'un autre candidat) : spinner. Quand le fetch est
  // désactivé (offre archivée sans profil résolu → aucun fetch en cours), le
  // placeholder EST le bon contenu et reste affiché.
  if (offer.isLoading || (offer.isPlaceholderData && offer.isFetching)) {
    return <Spinner />;
  }
  if (offer.error) return <ErrorBox message={offer.error.message} />;
  if (!offer.data) return null;

  const o = offer.data;
  const match = o.match;
  const noProfile = !profiles.isLoading && profiles.data?.length === 0;

  // Scores de l'offre par profil (source du badge et des indicateurs CV/lettre
  // du menu candidats).
  const scoreDetailById = new Map(
    o.scores.map((s) => [s.candidate_profile_id, s]),
  );
  // Options du menu candidats : offre archivée → profils déjà matchés (o.scores,
  // score toujours présent) ; offre active → tous les profils (score s'il existe).
  const candidateOptions = o.archived
    ? o.scores.map((s) => {
        const p = profiles.data?.find((x) => x.id === s.candidate_profile_id);
        return {
          id: s.candidate_profile_id,
          label: s.profile_name ?? p?.profile_name ?? "Profil",
          isActive: p?.is_active ?? false,
          score: s.total_score,
          hasCv: s.has_cv,
          hasLetter: s.has_letter,
          applicationSubmitted: s.application_submitted,
        };
      })
    : (profiles.data ?? []).map((p) => {
        const s = scoreDetailById.get(p.id);
        return {
          id: p.id,
          label: p.profile_name,
          isActive: p.is_active,
          score: s?.total_score ?? null,
          hasCv: s?.has_cv ?? false,
          hasLetter: s?.has_letter ?? false,
          applicationSubmitted: s?.application_submitted ?? false,
        };
      });

  const selectedProfileName =
    profiles.data?.find((p) => p.id === resolvedProfileId)?.profile_name ??
    o.scores.find((s) => s.candidate_profile_id === resolvedProfileId)
      ?.profile_name ??
    "le profil sélectionné";

  return (
    <div>
      <Link
        href={o.archived ? "/offers/archived" : "/offers"}
        className="text-sm text-zinc-500 underline"
      >
        {o.archived ? "← Retour aux offres archivées" : "← Retour aux offres"}
      </Link>

      <div className="mt-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <h1 className="truncate text-xl font-semibold text-zinc-900">
              {o.title ?? o.source_job_id}
            </h1>
            {o.archived && <Badge tone="amber">archivée</Badge>}
          </div>
          <Button
            variant={o.archived ? "success" : "danger"}
            disabled={archive.isPending}
            onClick={() => archive.mutate()}
          >
            {archive.isPending
              ? "…"
              : o.archived
                ? "Désarchiver"
                : "Archiver"}
          </Button>
        </div>
        <p className="mt-1 text-sm text-zinc-600">
          {[o.company, o.location, o.contract_type].filter(Boolean).join(" · ") || "—"}
        </p>
        {/* Date de publication, entre l'entreprise et le lien vers l'annonce. */}
        {o.published_date && (
          <p className="mt-1 text-xs text-zinc-400">
            Publiée le {formatDate(o.published_date)}
          </p>
        )}
        {o.url && (
          <a
            href={o.url}
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-block text-xs text-sky-600 underline"
          >
            Voir l&apos;annonce
          </a>
        )}
        {archive.error && (
          <div className="mt-2">
            <ErrorBox message={archive.error.message} />
          </div>
        )}
      </div>

      {/* Navigation précédente/suivante, au-dessus de la description, alignée à droite. */}
      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="secondary"
            disabled={prevHref == null}
            onClick={() => {
              if (prevHref) {
                setProfileId(null);
                router.push(prevHref, { scroll: false });
              }
            }}
            title="Offre précédente (flèche gauche)"
          >
            ← Offre précédente
          </Button>
          <Button
            variant="secondary"
            disabled={nextHref == null}
            onClick={() => {
              if (nextHref) {
                setProfileId(null);
                router.push(nextHref, { scroll: false });
              }
            }}
            title="Offre suivante (flèche droite)"
          >
            Offre suivante →
          </Button>
        </div>
      </div>

      {/* items-start : sans étirement, la carte Matching rapporte sa hauteur
          naturelle (sinon elle est étirée à la hauteur de la rangée, pilotée
          par la Description — le ResizeObserver mesurerait alors une hauteur
          déjà gonflée et la Description n'aurait jamais de scrollbar). */}
      <div className="mt-6 grid items-start gap-6 lg:grid-cols-2">
        {/* Description */}
        <Card ref={descCardRef} className="flex min-h-[24rem] flex-col p-4">
          <div className="text-sm font-medium text-zinc-900">Description</div>
          {/* La carte s'aligne sur la hauteur de la carte Matching (stretch de la
              grille) : le texte occupe l'espace restant (flex-1) et y défile. */}
          <p className="mt-2 min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap text-sm text-zinc-600">
            {o.description ?? "—"}
          </p>
          {o.skills_extracted && (
            <div className="mt-auto flex flex-wrap gap-1.5 pt-3">
              {Object.entries(o.skills_extracted)
                .filter(([, v]) => Array.isArray(v))
                .flatMap(([, v]) =>
                  (v as Array<{ name?: string }>).map((s) => s?.name).filter(Boolean),
                )
                .map((s) => (
                  <span
                    key={s}
                    className="rounded-md bg-zinc-100 px-2 py-0.5 text-xs text-zinc-700"
                  >
                    {s}
                  </span>
                ))}
            </div>
          )}
        </Card>

        {/* Matching — masquée si offre archivée sans aucun profil matché. */}
        {o.archived && o.scores.length === 0 ? null : (
          <Card ref={matchCardRef} className="min-h-[24rem] p-4">
            <div className="text-sm font-medium text-zinc-900">Matching</div>

            <div className="mt-3">
              <ProfileSelect
                options={candidateOptions}
                value={resolvedProfileId}
                onChange={setProfileId}
                disabled={profiles.isLoading || noProfile}
              />
            </div>

            {!match && (
              <div className="mt-4">
                {noProfile ? (
                  <p className="text-sm text-zinc-500">
                    Aucun profil candidat : uploadez d&apos;abord un CV.
                  </p>
                ) : o.archived ? (
                  <p className="text-sm text-zinc-500">
                    Aucun score calculé pour ce profil.
                  </p>
                ) : (
                  <>
                    <p className="text-sm text-zinc-500">
                      Aucun score calculé pour cette offre ({selectedProfileName}).
                    </p>
                    <Button
                      className="mt-3"
                      disabled={runMatch.isPending || resolvedProfileId === null}
                      onClick={() => runMatch.mutate()}
                    >
                      {runMatch.isPending
                        ? "Matching en cours…"
                        : "Lancer le matching"}
                    </Button>
                    {runMatch.error && (
                      <div className="mt-3">
                        <ErrorBox message={runMatch.error.message} />
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {match && (
              <div className="mt-4 space-y-4">
                <div className="flex items-end gap-3">
                  <span
                    className={`inline-flex items-center rounded-md px-3 py-1 text-3xl font-bold tabular-nums ${scoreBadgeClass(match.total_score)}`}
                  >
                    {Math.round(match.total_score)}
                  </span>
                  <span className="pb-1 text-sm text-zinc-400">/ 100</span>
                </div>
                <p className="text-xs text-zinc-400">
                  Score pour {selectedProfileName}.
                </p>

                <ScoreBreakdown breakdown={match.score_breakdown} />

                {match.explanation && (
                  <p className="text-sm text-zinc-600">{match.explanation}</p>
                )}

                {match.strengths.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-zinc-500">Forces</p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-emerald-700">
                      {match.strengths.map((s) => (
                        <li key={s}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {match.weaknesses.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-zinc-500">
                      Points de vigilance
                    </p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-amber-700">
                      {match.weaknesses.map((w) => (
                        <li key={w}>{w}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {match.missing_skills.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-zinc-500">
                      Compétences manquantes
                    </p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-rose-700">
                      {match.missing_skills.map((s) => (
                        <li key={s}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Date du matching, au-dessus des actions. */}
                <p className="text-xs text-zinc-400">
                  Matching effectué le {formatDateTime(match.created_at)}
                </p>

                {/* Actions : désactivées sur une offre archivée (lecture seule). */}
                {!o.archived && (
                  <div className="flex flex-wrap gap-2 pt-1">
                    <Button
                      variant="danger"
                      disabled={deleteMatch.isPending}
                      onClick={() => setConfirmDelete("match")}
                    >
                      {deleteMatch.isPending
                        ? "Suppression…"
                        : "Supprimer le matching"}
                    </Button>
                    {/* Aucun CV pour le couple → générer ; sinon → supprimer le
                        CV généré (le matching, lui, est conservé). */}
                    {cvs.length === 0 ? (
                      <Button
                        disabled={genCv.isPending}
                        onClick={() => genCv.mutate()}
                      >
                        {genCv.isPending ? "Génération…" : "Générer un CV"}
                      </Button>
                    ) : (
                      <Button
                        variant="danger"
                        disabled={deleteCv.isPending}
                        onClick={() => setConfirmDelete("cv")}
                      >
                        {deleteCv.isPending
                          ? "Suppression…"
                          : "Supprimer le CV"}
                      </Button>
                    )}
                    {/* Aucune lettre pour le couple → générer ; sinon → supprimer
                        la lettre générée (le matching, lui, est conservé). */}
                    {letters.length === 0 ? (
                      <Button
                        disabled={genLetter.isPending}
                        onClick={() => genLetter.mutate()}
                      >
                        {genLetter.isPending
                          ? "Génération…"
                          : "Générer une lettre de motivation"}
                      </Button>
                    ) : (
                      <Button
                        variant="danger"
                        disabled={deleteLetter.isPending}
                        onClick={() => setConfirmDelete("letter")}
                      >
                        {deleteLetter.isPending
                          ? "Suppression…"
                          : "Supprimer la lettre de motivation"}
                      </Button>
                    )}
                  </div>
                )}
                {runMatch.error && (
                  <div className="mt-2">
                    <ErrorBox message={runMatch.error.message} />
                  </div>
                )}
                {genCv.error && (
                  <div className="mt-2">
                    <ErrorBox message={genCv.error.message} />
                  </div>
                )}
                {deleteCv.error && (
                  <div className="mt-2">
                    <ErrorBox message={deleteCv.error.message} />
                  </div>
                )}
                {genLetter.error && (
                  <div className="mt-2">
                    <ErrorBox message={genLetter.error.message} />
                  </div>
                )}
                {deleteLetter.error && (
                  <div className="mt-2">
                    <ErrorBox message={deleteLetter.error.message} />
                  </div>
                )}
                {deleteMatch.error && (
                  <div className="mt-2">
                    <ErrorBox message={deleteMatch.error.message} />
                  </div>
                )}
                {genCv.isSuccess && (
                  <p className="text-sm text-emerald-700">CV généré.</p>
                )}
                {genLetter.isSuccess && (
                  <p className="text-sm text-emerald-700">Lettre générée.</p>
                )}
              </div>
            )}
          </Card>
        )}
      </div>

      {/* CV généré + lettre de motivation générée (aperçus, Markdown). Mêmes
          largeurs que les cards Description/Matching (lg:grid-cols-2) ; quand
          un seul des deux documents existe, il s'étend sur les deux colonnes. */}
      {(cvs.length > 0 || letters.length > 0) && (
        <div className="mt-6 grid items-start gap-6 lg:grid-cols-2">
          {cvs.length > 0 && (
            <Card
              ref={cvCardRef}
              className={`p-4 ${
                letters.length > 0 ? "flex min-h-[24rem] flex-col" : ""
              } ${letters.length === 0 ? "lg:col-span-2" : ""}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex flex-wrap items-baseline gap-x-2 text-sm font-medium text-zinc-900">
                  CV généré
                  {cvs[0]?.created_at && (
                    <span className="text-xs font-normal text-zinc-400">
                      le {formatDateTime(cvs[0].created_at)}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {/* Suivi « candidature envoyée » : bouton tant que non marquée,
                      badge vert cliquable une fois marquée (revertible). */}
                  {cvs[0]?.application_submitted ? (
                    <button
                      type="button"
                      onClick={() => setSubmitted.mutate()}
                      disabled={setSubmitted.isPending}
                      title="Candidature envoyée — cliquer pour annuler"
                      className="inline-flex items-center whitespace-nowrap rounded-full bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-800 hover:bg-emerald-200 disabled:opacity-50"
                    >
                      Candidature envoyée ✓
                    </button>
                  ) : (
                    <Button
                      variant="secondary"
                      disabled={setSubmitted.isPending}
                      onClick={() => setSubmitted.mutate()}
                    >
                      {setSubmitted.isPending
                        ? "…"
                        : "Candidature envoyée"}
                    </Button>
                  )}
                  {/* Téléchargement du CV généré en PDF (endpoint serveur). */}
                  <Button
                    href={`/api/v1/cvs/${activeCvId}/pdf`}
                    download
                    variant="secondary"
                  >
                    Télécharger en PDF
                  </Button>
                </div>
              </div>
              <div
                className={`mt-3 ${
                  letters.length > 0 ? "flex min-h-0 flex-1 flex-col" : ""
                }`}
              >
                {activeCv.isLoading ? (
                  <Spinner />
                ) : activeCv.error ? (
                  <ErrorBox message={activeCv.error.message} />
                ) : activeCv.data?.cv_text ? (
                  <Markdown
                    content={activeCv.data.cv_text}
                    className={`rounded-md border border-zinc-200 bg-white p-4 ${
                      letters.length > 0
                        ? "min-h-0 flex-1 overflow-y-auto"
                        : "max-h-[36rem] overflow-y-auto"
                    }`}
                  />
                ) : null}
              </div>
            </Card>
          )}

          {letters.length > 0 && (
            <Card
              ref={letterCardRef}
              className={`p-4 ${
                cvs.length > 0 ? "flex min-h-[24rem] flex-col" : ""
              } ${cvs.length === 0 ? "lg:col-span-2" : ""}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex flex-wrap items-baseline gap-x-2 text-sm font-medium text-zinc-900">
                  Lettre de motivation générée
                  {letters[0]?.created_at && (
                    <span className="text-xs font-normal text-zinc-400">
                      le {formatDateTime(letters[0].created_at)}
                    </span>
                  )}
                </div>
                {/* Copie de la lettre : elle est destinée à être collée dans un
                    document ou un email (pas de PDF). */}
                <Button
                  variant="secondary"
                  disabled={!activeLetter.data?.letter_text}
                  onClick={() => copyLetter()}
                >
                  {copied ? "Copié ✓" : "Copier"}
                </Button>
              </div>
              <div
                className={`mt-3 ${
                  cvs.length > 0 ? "flex min-h-0 flex-1 flex-col" : ""
                }`}
              >
                {activeLetter.isLoading ? (
                  <Spinner />
                ) : activeLetter.error ? (
                  <ErrorBox message={activeLetter.error.message} />
                ) : activeLetter.data?.letter_text ? (
                  <Markdown
                    content={activeLetter.data.letter_text}
                    className={`rounded-md border border-zinc-200 bg-white p-4 ${
                      cvs.length > 0
                        ? "min-h-0 flex-1 overflow-y-auto"
                        : "max-h-[36rem] overflow-y-auto"
                    }`}
                  />
                ) : null}
              </div>
            </Card>
          )}
        </div>
      )}

      {/* Confirmation de suppression (modale) : CV seul, lettre seule ou
          matching + documents associés. */}
      <Modal
        open={confirmDelete !== null}
        onClose={() => setConfirmDelete(null)}
        title={
          confirmDelete === "cv"
            ? "Supprimer le CV"
            : confirmDelete === "letter"
              ? "Supprimer la lettre de motivation"
              : "Supprimer le matching"
        }
      >
        {/* Chaque phrase sur sa propre ligne (whitespace-pre-line). */}
        <p className="whitespace-pre-line text-sm text-zinc-600">
          {confirmDelete === "cv"
            ? "Supprimer ce CV généré ?\nLe matching (score) est conservé.\n\nCette action est irréversible."
            : confirmDelete === "letter"
              ? "Supprimer cette lettre de motivation ?\nLe matching (score) et le CV sont conservés.\n\nCette action est irréversible."
              : "Supprimer ce matching et les CV et lettres associés ?\nL'offre redevient vierge pour ce profil.\n\nCette action est irréversible."}
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirmDelete(null)}>
            Annuler
          </Button>
          <Button
            variant="danger"
            disabled={
              confirmDelete === "cv"
                ? deleteCv.isPending
                : confirmDelete === "letter"
                  ? deleteLetter.isPending
                  : deleteMatch.isPending
            }
            onClick={() => {
              if (confirmDelete === "cv") deleteCv.mutate();
              else if (confirmDelete === "letter") deleteLetter.mutate();
              else if (confirmDelete === "match") deleteMatch.mutate();
              setConfirmDelete(null);
            }}
          >
            Supprimer
          </Button>
        </div>
      </Modal>
    </div>
  );
}
