-- Schéma applicatif du système de matching.
-- Source de vérité : les modèles SQLAlchemy (src/infrastructure/db/models/) en sont le reflet.
-- DDL idempotent : peut être ré-appliqué sans erreur.

CREATE TABLE IF NOT EXISTS job_offer (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(100) NOT NULL,
    source_job_id VARCHAR(255) NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    company TEXT,
    location TEXT,
    contract_type VARCHAR(100),
    published_date DATE,
    experience TEXT,
    diploma TEXT,
    description TEXT,
    skills_extracted JSONB,
    raw_payload JSONB,
    content_hash VARCHAR(64),
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    archived_at TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_job_offer_source_external UNIQUE (source, source_job_id),
    CONSTRAINT chk_job_offer_url CHECK (url <> ''),
    CONSTRAINT chk_job_offer_raw_payload CHECK (
        JSONB_TYPEOF(raw_payload) = 'object'
    ),
    CONSTRAINT chk_job_offer_skills_object CHECK (
        JSONB_TYPEOF(skills_extracted) = 'object'
    )
);

CREATE TABLE IF NOT EXISTS candidate_profile (
    id BIGSERIAL PRIMARY KEY,
    profile_name VARCHAR(200) NOT NULL,
    headline TEXT,
    summary TEXT,
    cv_raw_json JSONB NOT NULL,
    skills JSONB NOT NULL DEFAULT '[]'::JSONB,
    experiences JSONB NOT NULL DEFAULT '[]'::JSONB,
    education JSONB NOT NULL DEFAULT '[]'::JSONB,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_candidate_profile_name UNIQUE (profile_name),
    CONSTRAINT chk_candidate_cv_raw_json CHECK (
        JSONB_TYPEOF(cv_raw_json) = 'object'
    ),
    CONSTRAINT chk_candidate_skills_array CHECK (
        JSONB_TYPEOF(skills) = 'array'
    ),
    CONSTRAINT chk_candidate_experiences_array CHECK (
        JSONB_TYPEOF(experiences) = 'array'
    ),
    CONSTRAINT chk_candidate_education_array CHECK (
        JSONB_TYPEOF(education) = 'array'
    )
);

-- Migration idempotente pour les bases déjà existantes (les CREATE TABLE IF NOT
-- EXISTS ci-dessus n'altèrent pas les tables créées avant l'ajout de la colonne).
-- Placé après le CREATE pour que le schéma s'applique aussi sur une base neuve.
ALTER TABLE candidate_profile ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE job_offer ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE job_offer ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS match_result (
    id BIGSERIAL PRIMARY KEY,
    job_offer_id BIGINT NOT NULL REFERENCES job_offer (id) ON DELETE CASCADE,
    candidate_profile_id BIGINT NOT NULL REFERENCES candidate_profile (
        id
    ) ON DELETE CASCADE,
    total_score NUMERIC(5, 2) NOT NULL,
    score_breakdown JSONB NOT NULL,
    strengths JSONB NOT NULL DEFAULT '[]'::JSONB,
    weaknesses JSONB NOT NULL DEFAULT '[]'::JSONB,
    missing_skills JSONB NOT NULL DEFAULT '[]'::JSONB,
    explanation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_match_unique_pair UNIQUE (job_offer_id, candidate_profile_id),
    CONSTRAINT chk_match_total_score CHECK (
        total_score >= 0 AND total_score <= 100
    ),
    CONSTRAINT chk_match_score_breakdown_object CHECK (
        JSONB_TYPEOF(score_breakdown) = 'object'
    ),
    CONSTRAINT chk_match_strengths_array CHECK (
        JSONB_TYPEOF(strengths) = 'array'
    ),
    CONSTRAINT chk_match_weaknesses_array CHECK (
        JSONB_TYPEOF(weaknesses) = 'array'
    ),
    CONSTRAINT chk_match_missing_skills_array CHECK (
        JSONB_TYPEOF(missing_skills) = 'array'
    )
);

CREATE TABLE IF NOT EXISTS cv_version (
    id BIGSERIAL PRIMARY KEY,
    job_offer_id BIGINT NOT NULL REFERENCES job_offer (id) ON DELETE CASCADE,
    candidate_profile_id BIGINT NOT NULL REFERENCES candidate_profile (
        id
    ) ON DELETE CASCADE,
    match_result_id BIGINT REFERENCES match_result (id) ON DELETE SET NULL,
    cv_content_json JSONB NOT NULL,
    cv_text TEXT,
    tailoring_notes JSONB NOT NULL DEFAULT '[]'::JSONB,
    -- Suivi « candidature envoyée » : marqué par l'utilisateur pour un couple
    -- (offre, profil) une fois le CV généré, préservé à la régénération du CV.
    application_submitted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cv_version_pair UNIQUE (
        job_offer_id, candidate_profile_id
    ),
    CONSTRAINT chk_cv_content_object CHECK (
        JSONB_TYPEOF(cv_content_json) = 'object'
    ),
    CONSTRAINT chk_cv_tailoring_notes_array CHECK (
        JSONB_TYPEOF(tailoring_notes) = 'array'
    )
);

-- Retrait du concept de « sélection » : la génération en masse de CV est
-- abandonnée, la colonne is_selected (match_result et cv_version) est supprimée.
-- Placé après les CREATE TABLE pour que le schéma s'applique aussi sur une base neuve.
ALTER TABLE match_result DROP COLUMN IF EXISTS is_selected;
ALTER TABLE cv_version DROP COLUMN IF EXISTS is_selected;

-- Retrait du stockage sur disque du CV généré : le CV n'est persisté qu'en base
-- (cv_content_json / cv_text), plus de fichier `.md` sur disque.
ALTER TABLE cv_version DROP COLUMN IF EXISTS file_path;

-- Retrait de la notion de version : un seul CV par couple (offre, profil).
-- Migration **one-shot** gardée par l'existence de ``uq_cv_version_pair`` : elle
-- déduplique (garde la ligne la plus récente par couple) puis pose la contrainte
-- unique. Rejouer le DELETE et le DROP/ADD à chaque ``ensure_schema`` prendrait
-- un verrou ACCESS EXCLUSIVE et reconstruirait l'index unique — pour une base
-- déjà migrée (ou neuve, où le CREATE TABLE pose déjà la contrainte), le
-- garde-fou rend le bloc no-op.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_cv_version_pair'
          AND conrelid = 'cv_version'::regclass
    ) THEN
        ALTER TABLE cv_version DROP CONSTRAINT IF EXISTS chk_cv_version_positive;
        ALTER TABLE cv_version DROP CONSTRAINT IF EXISTS uq_cv_version;
        DELETE FROM cv_version a
        USING cv_version b
        WHERE a.job_offer_id = b.job_offer_id
          AND a.candidate_profile_id = b.candidate_profile_id
          AND a.id < b.id;
        ALTER TABLE cv_version DROP COLUMN IF EXISTS version_number;
        ALTER TABLE cv_version ADD CONSTRAINT uq_cv_version_pair
            UNIQUE (job_offer_id, candidate_profile_id);
    END IF;
END
$$;


-- ``CREATE INDEX CONCURRENTLY IF NOT EXISTS`` ne répare pas un index devenu
-- INVALID (création concurrente interrompue) : il « existe » déjà pour le
-- ``IF NOT EXISTS`` mais PostgreSQL ne l'utilisera jamais. On purge ces index
-- avant de les recréer — un index INVALID n'est consulté par aucune requête,
-- le DROP non-concurrent est donc sans contention. Tables possédant des
-- ``CREATE INDEX CONCURRENTLY`` dans ce fichier (les index non-concurrents,
-- ex. ``uq_candidate_profile_active``, ne peuvent pas devenir INVALID).
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT c.relname AS index_name
        FROM pg_index x
        JOIN pg_class c ON c.oid = x.indexrelid
        JOIN pg_class t ON t.oid = x.indrelid
        WHERE NOT x.indisvalid
          AND t.relname IN ('job_offer', 'match_result', 'cv_version', 'letter_version')
    LOOP
        EXECUTE format('DROP INDEX %I', r.index_name);
    END LOOP;
END
$$;


CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_job_offer_source ON job_offer (source);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_job_offer_company ON job_offer (company);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_job_offer_published_date ON job_offer (
    published_date
);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_job_offer_contract_type ON job_offer (
    contract_type
);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_job_offer_content_hash ON job_offer (
    content_hash
);
-- Colonne `url` interrogée par l'ingestion par URL (get_by_url / existing_urls).
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_job_offer_url ON job_offer (url);

-- Un seul profil actif garanti par la base (is_active unique quand il est vrai).
CREATE UNIQUE INDEX IF NOT EXISTS uq_candidate_profile_active
    ON candidate_profile (is_active) WHERE is_active;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_match_result_job_offer_id ON match_result (
    job_offer_id
);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_match_result_candidate_profile_id ON match_result (
    candidate_profile_id
);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cv_version_job_offer_id ON cv_version (
    job_offer_id
);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cv_version_candidate_profile_id ON cv_version (
    candidate_profile_id
);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cv_version_match_result_id ON cv_version (
    match_result_id
);

-- Lettre de motivation : une par couple (offre, profil), générée à la demande
-- par le LLM à partir de l'offre et du CV généré (fallback : CV brut du profil).
CREATE TABLE IF NOT EXISTS letter_version (
    id BIGSERIAL PRIMARY KEY,
    job_offer_id BIGINT NOT NULL REFERENCES job_offer (id) ON DELETE CASCADE,
    candidate_profile_id BIGINT NOT NULL REFERENCES candidate_profile (
        id
    ) ON DELETE CASCADE,
    match_result_id BIGINT REFERENCES match_result (id) ON DELETE SET NULL,
    letter_content_json JSONB NOT NULL,
    letter_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_letter_version_pair UNIQUE (
        job_offer_id, candidate_profile_id
    ),
    CONSTRAINT chk_letter_content_object CHECK (
        JSONB_TYPEOF(letter_content_json) = 'object'
    )
);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_letter_version_job_offer_id ON letter_version (
    job_offer_id
);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_letter_version_candidate_profile_id ON letter_version (
    candidate_profile_id
);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_letter_version_match_result_id ON letter_version (
    match_result_id
);

-- Suivi « candidature envoyée » sur cv_version (bases déjà existantes) :
-- une colonne par couple (offre, profil), préservée à la régénération du CV.
-- Placé après le CREATE pour que le schéma s'applique aussi sur une base neuve.
ALTER TABLE cv_version ADD COLUMN IF NOT EXISTS application_submitted BOOLEAN NOT NULL DEFAULT FALSE;

-- Paramètres de recherche : critères de recherche sauvegardés par l'utilisateur
-- (titre, source, URL). Nom de table pluriel assumé (choix utilisateur), qui
-- déroge à la convention singulier du reste du schéma — à conserver tel quel.
-- max_offers : nombre maximal d'offres nouvelles ingérées par l'agent de
-- recherche pour une URL de liste (slider 1 → 20 de l'interface, défaut 5).
CREATE TABLE IF NOT EXISTS search_parameters (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    source VARCHAR(100) NOT NULL,
    url TEXT NOT NULL,
    max_offers INTEGER NOT NULL DEFAULT 5,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_search_parameters_url UNIQUE (url),
    CONSTRAINT chk_search_parameters_max_offers CHECK (
        max_offers >= 1 AND max_offers <= 20
    )
);

-- Migration idempotente pour les bases déjà existantes (les CREATE TABLE IF NOT
-- EXISTS ci-dessus n'altèrent pas les tables créées avant l'ajout de la colonne).
ALTER TABLE search_parameters ADD COLUMN IF NOT EXISTS max_offers INTEGER NOT NULL DEFAULT 5;
ALTER TABLE search_parameters ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
-- Défaut documenté de max_offers = 5 (un éventuel DEFAULT 20 hérité d'un schéma
-- antérieur est corrigé sans toucher aux valeurs existantes).
ALTER TABLE search_parameters ALTER COLUMN max_offers SET DEFAULT 5;
ALTER TABLE search_parameters DROP CONSTRAINT IF EXISTS chk_search_parameters_max_offers;
ALTER TABLE search_parameters ADD CONSTRAINT chk_search_parameters_max_offers
    CHECK (max_offers >= 1 AND max_offers <= 20);

ALTER TABLE job_offer ALTER COLUMN contract_type TYPE VARCHAR(200);