import { Nav } from "@/components/nav";
import { QueryProvider } from "@/components/query-provider";
import { ArchivedDetailProvider } from "@/components/archived-detail-context";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <QueryProvider>
      <ArchivedDetailProvider>
        <div className="flex min-h-screen">
          <Nav />
          <main className="flex-1 bg-zinc-50 p-6">{children}</main>
        </div>
      </ArchivedDetailProvider>
    </QueryProvider>
  );
}
