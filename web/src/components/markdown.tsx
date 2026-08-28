"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ReactNode } from "react";

// Rendu Markdown stylé (palette zinc, cohérent avec le reste de l'interface).
// Le HTML brut n'est pas rendu (réchappe) : contenu uploadé traité comme du texte.
const components = {
  h1: ({ children }: { children?: ReactNode }) => (
    <h1 className="mb-2 text-xl font-semibold text-zinc-900">{children}</h1>
  ),
  h2: ({ children }: { children?: ReactNode }) => (
    <h2 className="mb-1.5 mt-4 text-base font-semibold text-zinc-900 first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }: { children?: ReactNode }) => (
    <h3 className="mb-1 mt-3 text-sm font-semibold text-zinc-900">{children}</h3>
  ),
  p: ({ children }: { children?: ReactNode }) => (
    <p className="my-2 text-sm leading-relaxed text-zinc-700">{children}</p>
  ),
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className="my-2 list-disc pl-5 text-sm text-zinc-700">{children}</ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="my-2 list-decimal pl-5 text-sm text-zinc-700">{children}</ol>
  ),
  li: ({ children }: { children?: ReactNode }) => <li className="my-0.5">{children}</li>,
  strong: ({ children }: { children?: ReactNode }) => (
    <strong className="font-semibold text-zinc-900">{children}</strong>
  ),
  em: ({ children }: { children?: ReactNode }) => <em className="italic">{children}</em>,
  a: ({ href, children }: { href?: string; children?: ReactNode }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-sky-600 underline"
    >
      {children}
    </a>
  ),
  code: ({ children }: { children?: ReactNode }) => (
    <code className="rounded bg-zinc-100 px-1 py-0.5 font-mono text-xs text-zinc-800">
      {children}
    </code>
  ),
  pre: ({ children }: { children?: ReactNode }) => (
    <pre className="my-2 overflow-x-auto rounded-md bg-zinc-50 p-3 text-xs leading-relaxed text-zinc-700">
      {children}
    </pre>
  ),
  hr: () => <hr className="my-3 border-zinc-200" />,
  blockquote: ({ children }: { children?: ReactNode }) => (
    <blockquote className="my-2 border-l-2 border-zinc-300 pl-3 text-sm text-zinc-600">
      {children}
    </blockquote>
  ),
  // Tableaux GFM (remark-gfm) : le CV généré met les compétences en tableau.
  table: ({ children }: { children?: ReactNode }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-sm text-zinc-700">
        {children}
      </table>
    </div>
  ),
  thead: ({ children }: { children?: ReactNode }) => (
    <thead className="bg-zinc-100 text-left">{children}</thead>
  ),
  tbody: ({ children }: { children?: ReactNode }) => <tbody>{children}</tbody>,
  tr: ({ children }: { children?: ReactNode }) => (
    <tr className="border-b border-zinc-200">{children}</tr>
  ),
  th: ({ children }: { children?: ReactNode }) => (
    <th className="px-2 py-1 align-top font-semibold text-zinc-900">{children}</th>
  ),
  td: ({ children }: { children?: ReactNode }) => (
    <td className="px-2 py-1 align-top">{children}</td>
  ),
};

export function Markdown({ content, className = "" }: { content: string; className?: string }) {
  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
