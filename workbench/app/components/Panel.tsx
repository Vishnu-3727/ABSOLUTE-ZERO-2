export function Panel({
  title,
  right,
  children,
  className = "",
}: {
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel flex flex-col p-4 ${className}`}>
      <header className="mb-3 flex items-center justify-between">
        <h2 className="panel-title">{title}</h2>
        {right}
      </header>
      {children}
    </section>
  );
}

const STATE_COLORS: Record<string, string> = {
  completed: "text-emerald-400",
  succeeded: "text-emerald-400",
  active: "text-sky-400",
  executing: "text-sky-400",
  pending: "text-amber-400",
  failed: "text-red-400",
  cancelled: "text-zinc-400",
  "not-executed": "text-zinc-500",
};

export function StatusPill({ state }: { state: string }) {
  return (
    <span
      className={`mono rounded border border-current/30 px-1.5 py-0.5 text-[10px] uppercase ${
        STATE_COLORS[state] ?? "text-[var(--text-dim)]"
      }`}
    >
      {state}
    </span>
  );
}

export function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-[var(--text-dim)]">
        {label}
      </div>
      <div className="mono glow text-xl text-sky-300">{value}</div>
    </div>
  );
}
