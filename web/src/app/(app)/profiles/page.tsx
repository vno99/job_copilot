"use client";

import { useRef, useState } from "react";
import type { QueryClient } from "@tanstack/react-query";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Markdown } from "@/components/markdown";
import { Badge, Button, Card, EmptyState, ErrorBox, Modal, Spinner } from "@/components/ui";

function invalidateProfiles(qc: QueryClient) {
  qc.invalidateQueries({ queryKey: ["profiles"] });
  qc.invalidateQueries({ queryKey: ["profile"] });
}

export default function ProfilesPage() {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [profileName, setProfileName] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const profiles = useQuery({ queryKey: ["profiles"], queryFn: api.getProfiles });
  const activeProfile = useQuery({
    queryKey: ["profile", "active"],
    queryFn: api.getActiveProfile,
    retry: false,
  });

  const upload = useMutation({
    mutationFn: (file: File) =>
      api.uploadProfile(file, profileName.trim() || undefined),
    onSuccess: () => {
      invalidateProfiles(qc);
      setProfileName("");
      if (fileRef.current) fileRef.current.value = "";
    },
  });

  // Activation directe depuis la liste (« Tous les profils ») : la coche à
  // gauche du nom rend le profil actif sans ouvrir le détail.
  const [activatingId, setActivatingId] = useState<number | null>(null);
  const activate = useMutation({
    mutationFn: (id: number) => api.activateProfile(id),
    onMutate: (id) => setActivatingId(id),
    onSettled: () => setActivatingId(null),
    onSuccess: () => invalidateProfiles(qc),
  });

  return (
    <div>
      <h1 className="text-xl font-semibold text-zinc-900">Profils candidats</h1>
      <p className="mt-1 text-sm text-zinc-500">
        Un CV (Markdown/HTML) uploadé crée un nouveau profil ; un seul profil est
        actif à la fois.
      </p>

      {/* Upload */}
      <Card className="mt-6 p-4">
        <div className="text-sm font-medium text-zinc-900">Uploader un CV</div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".md,.markdown,.html,.htm,text/markdown,text/html"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) upload.mutate(file);
            }}
            className="text-sm text-zinc-600 file:mr-2 file:rounded-md file:border-0 file:bg-zinc-900 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white hover:file:bg-zinc-700"
          />
          <input
            type="text"
            value={profileName}
            onChange={(e) => setProfileName(e.target.value)}
            placeholder="Nom du profil (optionnel)"
            className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm"
          />
        </div>
        {upload.isPending && (
          <p className="mt-2 text-sm text-zinc-500">Upload en cours…</p>
        )}
        {upload.error && <ErrorBox message={upload.error.message} />}
        {upload.isSuccess && (
          <p className="mt-2 text-sm text-emerald-700">CV uploadé.</p>
        )}
      </Card>

      {/* Profil actif (détail) */}
      <Card className="mt-6 p-4">
        <div className="text-sm font-medium text-zinc-900">Profil actif</div>
        {activeProfile.isLoading && <Spinner />}
        {activeProfile.error && (
          <p className="mt-2 text-sm text-zinc-500">Aucun profil actif.</p>
        )}
        {activeProfile.data && (
          <>
            <button
              type="button"
              onClick={() => setSelectedId(activeProfile.data!.id)}
              className="mt-3 block w-full cursor-pointer text-left"
            >
              <div className="flex items-center gap-2">
                <span className="font-semibold text-zinc-900">
                  {activeProfile.data.profile_name}
                </span>
                <Badge tone="green">actif</Badge>
              </div>
              {activeProfile.data.headline &&
                activeProfile.data.headline !== activeProfile.data.profile_name && (
                  <p className="mt-0.5 text-xs text-zinc-500">
                    {activeProfile.data.headline}
                  </p>
                )}
            </button>

            {activeProfile.data.skills.length > 0 && (
              <div
                className="flex flex-wrap gap-1.5 pt-1"
                onClick={(e) => e.stopPropagation()}
              >
                {activeProfile.data.skills.map((s) => (
                  <span
                    key={s}
                    className="cursor-default rounded-md bg-zinc-100 px-2 py-0.5 text-xs text-zinc-700"
                  >
                    {s}
                  </span>
                ))}
              </div>
            )}
          </>
        )}
      </Card>

      {/* Liste des profils */}
      <div className="mt-6">
        <div className="text-sm font-medium text-zinc-900">Tous les profils</div>
        {profiles.isLoading && <Spinner />}
        {profiles.error && <ErrorBox message={profiles.error.message} />}
        {profiles.data?.length === 0 && (
          <EmptyState>Aucun profil pour le moment.</EmptyState>
        )}
        <div className="mt-3 space-y-2">
          {profiles.data?.map((p) => (
            <Card key={p.id} className="flex items-center gap-3 px-4 py-3">
              <button
                type="button"
                onClick={() => activate.mutate(p.id)}
                disabled={p.is_active || activatingId !== null}
                title={
                  p.is_active
                    ? "Profil actif"
                    : `Rendre « ${p.profile_name} » actif`
                }
                aria-label={
                  p.is_active
                    ? `${p.profile_name} est le profil actif`
                    : `Rendre ${p.profile_name} actif`
                }
                className={`group inline-flex items-center justify-center rounded-full p-1 transition-colors ${
                  p.is_active
                    ? "cursor-default"
                    : "cursor-pointer hover:bg-emerald-50"
                }`}
              >
                {p.is_active ? (
                  <svg
                    viewBox="0 0 20 20"
                    className="h-5 w-5 text-emerald-600"
                    aria-hidden="true"
                  >
                    <circle cx="10" cy="10" r="9" fill="currentColor" />
                    <path
                      d="M6.5 10.5l2.3 2.3 4.7-4.7"
                      fill="none"
                      stroke="#fff"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                ) : activatingId === p.id ? (
                  <span className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-600" />
                ) : (
                  <svg
                    viewBox="0 0 20 20"
                    className="h-5 w-5 text-zinc-300 transition-colors group-hover:text-emerald-600"
                    aria-hidden="true"
                  >
                    <circle
                      cx="10"
                      cy="10"
                      r="8"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    />
                  </svg>
                )}
              </button>
              <button
                type="button"
                onClick={() => setSelectedId(p.id)}
                className="cursor-pointer text-sm font-medium text-zinc-900 hover:underline"
                title="Ouvrir le détail"
              >
                {p.profile_name}
              </button>
              {p.is_active && <Badge tone="green">actif</Badge>}
              <button
                type="button"
                onClick={() => setSelectedId(p.id)}
                className="cursor-pointer text-xs text-zinc-400 hover:underline"
                title="Ouvrir le détail"
              >
                Ajouté le {new Date(p.created_at).toLocaleString("fr-FR")}
              </button>
            </Card>
          ))}
          {activate.error && (
            <ErrorBox message={activate.error.message} />
          )}
        </div>
      </div>

      {selectedId !== null && (
        <ProfileModal
          key={selectedId}
          id={selectedId}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}

function ProfileModal({ id, onClose }: { id: number; onClose: () => void }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState("");
  const [cvView, setCvView] = useState<"apercu" | "source">("apercu");

  const profile = useQuery({
    queryKey: ["profile", id],
    queryFn: () => api.getProfile(id),
  });

  const invalidate = () => invalidateProfiles(qc);

  const activate = useMutation({
    mutationFn: () => api.activateProfile(id),
    onSuccess: invalidate,
  });
  const rename = useMutation({
    mutationFn: (name: string) => api.renameProfile(id, name),
    onSuccess: () => {
      invalidate();
      setEditing(false);
    },
  });

  if (profile.isLoading) {
    return (
      <Modal open onClose={onClose} title="Profil">
        <Spinner />
      </Modal>
    );
  }
  if (profile.error) {
    return (
      <Modal open onClose={onClose} title="Profil">
        <ErrorBox message={profile.error.message} />
      </Modal>
    );
  }
  if (!profile.data) return null;

  const p = profile.data;

  const startEdit = () => {
    setEditValue(p.profile_name);
    setEditing(true);
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={
        <span className="flex items-center gap-2">
          {p.headline ?? p.profile_name}
          {p.is_active && <Badge tone="green">actif</Badge>}
        </span>
      }
    >
      <div className="space-y-4">
        {/* Nom + actions */}
        <div className="flex flex-wrap items-center gap-2">
          {editing ? (
            <>
              <input
                type="text"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                className="w-64 rounded-md border border-zinc-300 px-3 py-1.5 text-sm"
              />
              <Button
                disabled={rename.isPending}
                onClick={() => rename.mutate(editValue.trim())}
              >
                Enregistrer
              </Button>
              <Button variant="ghost" onClick={() => setEditing(false)}>
                Annuler
              </Button>
            </>
          ) : (
            <>
              <span className="font-semibold text-zinc-900">{p.profile_name}</span>
              <Button variant="secondary" onClick={startEdit}>
                Renommer
              </Button>
              {p.is_active ? (
                <Button
                  variant="secondary"
                  disabled
                  title="Le profil actif ne peut pas être désactivé : activez d'abord un autre profil"
                >
                  Désactiver
                </Button>
              ) : (
                <Button
                  disabled={activate.isPending}
                  onClick={() => activate.mutate()}
                >
                  Activer
                </Button>
              )}
            </>
          )}
        </div>

        {p.is_active && (
          <p className="text-xs text-zinc-500">
            Le profil actif ne peut pas être désactivé : activez un autre profil
            pour lui retirer son statut actif.
          </p>
        )}

        {rename.error && <ErrorBox message={rename.error.message} />}
        {activate.error && <ErrorBox message={activate.error.message} />}

        {/* CV : aperçu Markdown ou source brute */}
        <div>
          <div className="flex items-center justify-end">
            {p.raw_content && (
              <div className="flex overflow-hidden rounded-md border border-zinc-200 text-xs">
                <button
                  type="button"
                  onClick={() => setCvView("apercu")}
                  className={`px-2.5 py-1 ${
                    cvView === "apercu"
                      ? "bg-zinc-900 font-medium text-white"
                      : "text-zinc-600 hover:bg-zinc-50"
                  }`}
                >
                  Aperçu
                </button>
                <button
                  type="button"
                  onClick={() => setCvView("source")}
                  className={`px-2.5 py-1 ${
                    cvView === "source"
                      ? "bg-zinc-900 font-medium text-white"
                      : "text-zinc-600 hover:bg-zinc-50"
                  }`}
                >
                  Source
                </button>
              </div>
            )}
          </div>
          {p.raw_content ? (
            cvView === "apercu" ? (
              <Markdown
                content={p.raw_content_markdown || p.raw_content}
                className="mt-2 rounded-md bg-zinc-50 p-3"
              />
            ) : (
              <pre className="mt-2 whitespace-pre-wrap break-words rounded-md bg-zinc-50 p-3 text-xs leading-relaxed text-zinc-700">
                {p.raw_content}
              </pre>
            )
          ) : (
            <p className="mt-2 text-sm text-zinc-500">(aucun contenu brut stocké)</p>
          )}
        </div>
      </div>
    </Modal>
  );
}
