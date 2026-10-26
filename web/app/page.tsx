export default function HomePage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <p className="text-sm font-semibold uppercase tracking-wide text-accent">SIH26263 · AICTE</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-foreground">
        APAAR Student Data &amp; Verification Platform
      </h1>
      <p className="mt-4 text-muted-foreground">
        Student-level enrolment reporting keyed on APAAR ID, with automatic validation, explainable
        fraud detection, and consent-based verification.
      </p>
      <div className="mt-8 rounded-lg border border-border bg-card p-5">
        <h2 className="text-sm font-semibold text-card-foreground">Services</h2>
        <ul className="mt-3 space-y-1.5 text-sm text-muted-foreground">
          <li>
            API ·{" "}
            <a className="text-primary underline" href="http://localhost:8000/docs">
              localhost:8000/docs
            </a>
          </li>
          <li>
            Mock APAAR registry ·{" "}
            <a className="text-primary underline" href="http://localhost:8001/docs">
              localhost:8001/docs
            </a>
          </li>
          <li>Web · localhost:3000</li>
        </ul>
      </div>
      <p className="mt-8 text-xs text-muted-foreground">
        The full portal UI is built in Steps 14–19 of <code>docs/PLAN.md</code>.
      </p>
    </main>
  );
}
