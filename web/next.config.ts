import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactCompiler: true,
  // Sortie "standalone" : build autonome utilisé par le Dockerfile multi-étapes
  // (voir node_modules/next/dist/docs/01-app/03-api-reference/05-config/01-next-config-js/output.md).
  output: "standalone",
  // Timeout du proxy vers l'API : le défaut Next.js est 30 s
  // (router-utils/proxy-request.js : ``proxyTimeout || 30000``). La génération
  // de CV/lettre est synchrone et fait 2 appels LLM (pass 1 + réécriture
  // humanisée de la pass 2) : elle dépasse régulièrement 30 s. Sans
  // ce réglage, Next.js coupe la connexion à 30 s (« socket hang up » côté
  // navigateur) alors que l'API, elle, termine et persiste quand même le CV.
  experimental: {
    proxyTimeout: 180000,
  },
  // Proxy serveur : le navigateur ne parle qu'à Next.js (pas de CORS), qui relaie
  // vers l'API FastAPI. API_URL est lu au runtime (localhost:8000 en dev, http://api:8000 en Docker).
  async rewrites() {
    const apiUrl = process.env.API_URL ?? "http://localhost:8000";
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiUrl}/api/v1/:path*`,
      },
    ];
  },
  // Pas de tableau de bord : la home redirige directement vers la rubrique Offres.
  async redirects() {
    return [{ source: "/", destination: "/offers", permanent: false }];
  },
};

export default nextConfig;
