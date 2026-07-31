import { LockKeyhole } from "lucide-react";

export default function OperatorPage() {
  return (
    <main className="mx-auto flex min-h-[70vh] max-w-3xl items-center px-6 py-16">
      <section className="elev-1 w-full rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--surface)] p-8">
        <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-full bg-[var(--surface-soft)] text-[var(--text-strong)]">
          <LockKeyhole aria-hidden="true" className="h-5 w-5" />
        </div>
        <p className="type-label mb-2 text-[var(--text-muted)]">Restricted operations</p>
        <h1 className="type-heading text-[var(--text-strong)]">Operator access is server-managed</h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-[var(--text-muted)]">
          This browser surface no longer accepts or stores privileged service credentials.
          Operator access will return through a server-side administrative boundary after
          the identity-aware gateway is configured.
        </p>
      </section>
    </main>
  );
}
