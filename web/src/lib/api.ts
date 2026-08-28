// Client API — aligné sur docs/api-contract.md.
// Toutes les requêtes passent par /api/v1/* (proxifié par les rewrites Next.js
// vers l'API FastAPI, côté serveur : pas de CORS navigateur).

export interface ProfileSummary {
  id: number;
  profile_name: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Profile extends ProfileSummary {
  headline: string | null;
  summary: string | null;
  skills: string[];
  experiences: Array<Record<string, unknown>>;
  education: string[];
  source_path: string;
  raw_content: string;
  raw_content_markdown: string;
  created_at: string;
}

export interface JobOfferScore {
  candidate_profile_id: number;
  profile_name: string | null;
  total_score: number;
  created_at: string;
  // Indicateurs d'artefacts générés pour le couple (offre, profil) : affichés
  // dans la cellule score (icônes non cliquables).
  has_cv: boolean;
  has_letter: boolean;
  // Suivi « candidature envoyée » pour le couple (drapeau du cv_version) :
  // la candidature a été déposée pour cette offre avec ce profil.
  application_submitted: boolean;
}

export interface JobOfferListItem {
  id: number;
  // Source d'ingestion de l'offre (ex. `hellowork`, nom de domaine de l'URL).
  source: string;
  title: string | null;
  company: string | null;
  location: string | null;
  contract_type: string | null;
  published_date: string | null;
  url: string;
  ingested_at: string;
  archived: boolean;
  // Scores de l'offre, tous profils confondus, du meilleur au plus faible puis
  // du plus récent au plus ancien. Une offre est matchée dès qu'elle a ≥1 score.
  scores: JobOfferScore[];
}

export interface JobOfferList {
  total: number;
  limit: number;
  offset: number;
  items: JobOfferListItem[];
}

// Retour de POST /job-offers/from-url et /job-offers/from-source : les offres
// persistées (une seule pour une page d'offre unique ou un contenu collé,
// plusieurs pour une liste) et les compteurs d'ingestion (added = nouvelles,
// already_present = déjà en base).
export interface AddOffersResult {
  offers: JobOfferListItem[];
  added: number;
  already_present: number;
}

export interface ScoreBreakdown extends Record<string, number> {
  title_score: number;
  skills_score: number;
  experience_score: number;
  education_score: number;
}

export interface MatchResult {
  id: number;
  job_offer_id: number;
  candidate_profile_id: number;
  total_score: number;
  score_breakdown: ScoreBreakdown;
  strengths: string[];
  weaknesses: string[];
  missing_skills: string[];
  explanation: string | null;
  created_at: string;
}

export interface CVSummary {
  id: number;
  match_result_id: number | null;
  // Suivi « candidature envoyée » : marqué par l'utilisateur une fois la
  // candidature déposée pour le couple (offre, profil).
  application_submitted: boolean;
  created_at: string;
}

export interface CVDetail extends CVSummary {
  job_offer_id: number;
  candidate_profile_id: number;
  cv_text: string | null;
  tailoring_notes: string[];
}

export interface LetterSummary {
  id: number;
  match_result_id: number | null;
  created_at: string;
}

export interface LetterDetail extends LetterSummary {
  job_offer_id: number;
  candidate_profile_id: number;
  letter_text: string | null;
}

export interface JobOfferDetail {
  id: number;
  source: string;
  source_job_id: string;
  title: string | null;
  company: string | null;
  location: string | null;
  contract_type: string | null;
  published_date: string | null;
  experience: string | null;
  diploma: string | null;
  description: string | null;
  skills_extracted: Record<string, unknown> | null;
  url: string;
  ingested_at: string;
  archived: boolean;
  archived_at: string | null;
  candidate_profile_id: number | null;
  // Offres précédente/suivante dans la liste (ingested_at DESC, id DESC),
  // même ensemble archivé/actif ; null aux extrémités.
  previous_offer_id: number | null;
  next_offer_id: number | null;
  match: MatchResult | null;
  // Profils ayant déjà matché avec l'offre (source du menu candidats d'une
  // offre archivée), du meilleur score au plus faible.
  scores: JobOfferScore[];
  // CV du couple (offre, profil résolu) — au plus un (un seul CV par couple).
  cvs: CVSummary[];
  // Lettre de motivation du couple (offre, profil résolu) — au plus une (une
  // seule lettre par couple).
  letters: LetterSummary[];
}

export interface CVGenerateResult {
  cv_id: number;
  score: number | null;
}

export interface LetterGenerateResult {
  letter_id: number;
  score: number | null;
}

export type SortField =
  | "title"
  | "company"
  | "location"
  | "source"
  | "ingested_at";

export interface OfferFilters {
  limit?: number;
  offset?: number;
  company?: string;
  source?: string;
  archived?: boolean;
  sortBy?: SortField;
  order?: "asc" | "desc";
}

export interface ArchiveResult {
  job_offer_id: number;
  archived: boolean;
  archived_at: string | null;
}

export interface SearchParameter {
  id: number;
  title: string;
  source: string;
  url: string;
  max_offers: number;
  // Actif = pris en compte par l'agent de recherche (activé à la création).
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SearchParameterInput {
  title: string;
  source: string;
  url: string;
  max_offers: number;
}

// Résultat de l'exécution de l'agent de recherche (POST /search-parameters/run
// et /search-parameters/{id}/run) — même pipeline que le DAG
// search_parameters_agent, synchrone. `parameters[]` détaille chaque recherche
// (statut + compteurs d'offres) ; le titre et la source permettent au front
// d'enrichir la bannière d'un run unitaire.
export interface SearchAgentParameterResult {
  id: number;
  title: string;
  source: string;
  url: string;
  max_offers: number;
  status: "ok" | "duplicate" | "scraping_failed" | "llm_failed" | "error";
  added?: number;
  already_present?: number;
}

export interface SearchAgentRunResult {
  total: number;
  succeeded: number;
  duplicates: number;
  scraping_failed: number;
  llm_failed: number;
  other_failed: number;
  added_offers: number;
  already_present: number;
  parameters: SearchAgentParameterResult[];
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    // FastAPI renvoie les erreurs de validation 422 comme un tableau de
    // {loc, msg, type} — on remonte le premier message utile au lieu d'un
    // « Unprocessable Entity » vide de sens.
    if (Array.isArray(body?.detail) && body.detail.length > 0) {
      const first = body.detail[0];
      if (typeof first?.msg === "string") return first.msg;
    }
  } catch {
    /* corps non JSON */
  }
  return res.statusText || `Erreur ${res.status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new Error(await parseError(res));
  // 204 No Content (ex. suppression) : pas de corps JSON à parser.
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  getProfiles: () => request<ProfileSummary[]>("/profiles"),
  getActiveProfile: () => request<Profile>("/profile"),
  getProfile: (id: number) => request<Profile>(`/profile/${id}`),
  activateProfile: (id: number) =>
    request<Profile>(`/profiles/${id}/activate`, { method: "PUT" }),
  renameProfile: (id: number, name: string) =>
    request<Profile>(`/profiles/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ profile_name: name }),
    }),

  uploadProfile: async (file: File, profileName?: string): Promise<Profile> => {
    const form = new FormData();
    form.append("file", file);
    if (profileName) form.append("profile_name", profileName);
    const res = await fetch("/api/v1/profiles", { method: "POST", body: form });
    if (!res.ok) throw new Error(await parseError(res));
    return res.json() as Promise<Profile>;
  },

  getOffers: (filters: OfferFilters = {}) => {
    const qs = new URLSearchParams();
    if (filters.limit != null) qs.set("limit", String(filters.limit));
    if (filters.offset != null) qs.set("offset", String(filters.offset));
    if (filters.company) qs.set("company", filters.company);
    if (filters.source) qs.set("source", filters.source);
    if (filters.archived != null) qs.set("archived", String(filters.archived));
    if (filters.sortBy) qs.set("sort_by", filters.sortBy);
    if (filters.order) qs.set("order", filters.order);
    return request<JobOfferList>(`/job-offers?${qs.toString()}`);
  },
  getOffer: (id: number, candidateProfileId?: number) => {
    const qs = new URLSearchParams();
    if (candidateProfileId != null)
      qs.set("candidate_profile_id", String(candidateProfileId));
    const query = qs.toString();
    return request<JobOfferDetail>(
      `/job-offers/${id}${query ? `?${query}` : ""}`,
    );
  },

  runMatch: (jobOfferId: number, candidateProfileId?: number) =>
    request<MatchResult>("/matching/run", {
      method: "POST",
      body: JSON.stringify({
        job_offer_id: jobOfferId,
        candidate_profile_id: candidateProfileId,
      }),
    }),

  // Supprime le matching d'un couple (offre, profil) et ses CV associés.
  deleteMatch: (jobOfferId: number, candidateProfileId?: number) => {
    const qs = new URLSearchParams();
    if (candidateProfileId != null)
      qs.set("candidate_profile_id", String(candidateProfileId));
    const query = qs.toString();
    return request<void>(
      `/matching/${jobOfferId}${query ? `?${query}` : ""}`,
      { method: "DELETE" },
    );
  },

  archiveOffer: (jobOfferId: number, archived: boolean) =>
    request<ArchiveResult>(`/job-offers/${jobOfferId}/archived`, {
      method: "PUT",
      body: JSON.stringify({ archived }),
    }),

  // Ingère les offres d'une URL : la page est récupérée côté serveur (Playwright)
  // puis les offres extraites par le LLM, jusqu'à `maxOffers` pour une liste.
  // `source` (optionnel) : contenu de la page collé par l'utilisateur — présent,
  // il remplace le fetch (offre unique, l'URL n'est jamais récupérée), ce qui
  // débloque les sites anti-bot (ex. Indeed/APEC) sans contournement automatisé.
  // 409 si l'URL est une offre unique déjà en base, 422 si l'URL est invalide ou
  // si la page n'est pas une offre, 413 si le `source` dépasse la borne, 502 si
  // le LLM est indisponible.
  addOfferFromUrl: (url: string, maxOffers: number, source?: string) =>
    request<AddOffersResult>("/job-offers/from-url", {
      method: "POST",
      body: JSON.stringify({
        url,
        max_offers: maxOffers,
        ...(source ? { source } : {}),
      }),
    }),

  generateCv: (jobOfferId: number, candidateProfileId?: number) =>
    request<CVGenerateResult>("/cvs/generate", {
      method: "POST",
      body: JSON.stringify({
        job_offer_id: jobOfferId,
        candidate_profile_id: candidateProfileId,
      }),
    }),

  // Supprime le CV généré du couple (offre, profil) — le matching est conservé.
  deleteCv: (jobOfferId: number, candidateProfileId?: number) => {
    const qs = new URLSearchParams();
    if (candidateProfileId != null)
      qs.set("candidate_profile_id", String(candidateProfileId));
    const query = qs.toString();
    return request<void>(
      `/job-offers/${jobOfferId}/cv${query ? `?${query}` : ""}`,
      { method: "DELETE" },
    );
  },

  // Détail d'un CV (``cv_text`` = Markdown généré par le LLM).
  getCv: (id: number) => request<CVDetail>(`/cvs/${id}`),

  // Bascule le suivi « candidature envoyée » d'un CV (état voulu, idempotent) ;
  // la bascule reste possible sur une offre archivée.
  setCvSubmitted: (cvId: number, submitted: boolean) =>
    request<CVSummary>(`/cvs/${cvId}/submitted`, {
      method: "PUT",
      body: JSON.stringify({ submitted }),
    }),

  // Génère la lettre de motivation du couple (offre, profil) via le LLM ; une
  // lettre existante pour le couple est remplacée (une seule lettre par couple).
  generateLetter: (jobOfferId: number, candidateProfileId?: number) =>
    request<LetterGenerateResult>("/letters/generate", {
      method: "POST",
      body: JSON.stringify({
        job_offer_id: jobOfferId,
        candidate_profile_id: candidateProfileId,
      }),
    }),

  // Supprime la lettre générée du couple (offre, profil) — le matching est conservé.
  deleteLetter: (jobOfferId: number, candidateProfileId?: number) => {
    const qs = new URLSearchParams();
    if (candidateProfileId != null)
      qs.set("candidate_profile_id", String(candidateProfileId));
    const query = qs.toString();
    return request<void>(
      `/job-offers/${jobOfferId}/letter${query ? `?${query}` : ""}`,
      { method: "DELETE" },
    );
  },

  // Détail d'une lettre (``letter_text`` = Markdown généré par le LLM).
  getLetter: (id: number) => request<LetterDetail>(`/letters/${id}`),

  // Paramètres de recherche (section « Paramètres de recherche » du menu).
  // L'URL est unique côté serveur (409 si déjà utilisée).
  getSearchParameters: () =>
    request<SearchParameter[]>("/search-parameters"),
  createSearchParameter: (data: SearchParameterInput) =>
    request<SearchParameter>("/search-parameters", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateSearchParameter: (id: number, data: SearchParameterInput) =>
    request<SearchParameter>(`/search-parameters/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  deleteSearchParameter: (id: number) =>
    request<void>(`/search-parameters/${id}`, { method: "DELETE" }),

  // Active / désactive un paramètre — un paramètre inactif est ignoré par
  // l'agent de recherche (DAG et bouton Exécuter).
  activateSearchParameter: (id: number) =>
    request<SearchParameter>(`/search-parameters/${id}/activate`, {
      method: "PUT",
    }),
  deactivateSearchParameter: (id: number) =>
    request<SearchParameter>(`/search-parameters/${id}/deactivate`, {
      method: "PUT",
    }),

  // Exécute l'agent de recherche immédiatement (même pipeline que le DAG
  // search_parameters_agent) : ingestion des offres de chaque URL des
  // paramètres actifs, résumé retourné en réponse (offres ajoutées, déjà
  // présentes, échecs par catégorie).
  runSearchAgent: () =>
    request<SearchAgentRunResult>("/search-parameters/run", { method: "POST" }),

  // Exécute une recherche précise, qu'elle soit active ou non (triangle par
  // ligne) : même pipeline que runSearchAgent pour une seule ligne, résumé
  // identique (parameters[0] porte titre/source). 404 si l'id est inconnu.
  runSearchParameter: (id: number) =>
    request<SearchAgentRunResult>(`/search-parameters/${id}/run`, {
      method: "POST",
    }),
};
