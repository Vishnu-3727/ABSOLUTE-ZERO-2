"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useUi } from "@/stores/ui";

// Wired sections navigate; unwired sections are shown disabled with the
// honest reason — the workbench never fakes a screen.
const SECTIONS: { label: string; href?: string; pending?: string }[] = [
  { label: "Dashboard", href: "/" },
  { label: "Requests", href: "/requests" },
  { label: "Workflow", href: "/workflow" },
  { label: "Communication Bus", href: "/bus" },
  { label: "Storage", href: "/storage" },
  { label: "Replay", href: "/replay" },
  { label: "Capability Planner", href: "/planner" },
  { label: "Execution Engine", href: "/execution" },
  { label: "Verification", pending: "VAE not wired (C3)" },
  { label: "Reasoning", pending: "RO not wired (C3)" },
  { label: "Learning", pending: "LIE not wired (C3)" },
  { label: "Governance", pending: "SGPE not wired (C3)" },
  { label: "Memory", pending: "UMS/CM not wired (C3)" },
  { label: "Plugin Runtime", pending: "PRT not wired (C3)" },
];

export function Nav() {
  const pathname = usePathname();
  const connected = useUi((s) => s.wsConnected);
  return (
    <nav className="panel flex h-full w-56 shrink-0 flex-col gap-0.5 p-3">
      <div className="mb-4 px-2">
        <div className="glow text-sm font-bold tracking-widest text-sky-300">
          ABSOLUTE-ZERO
        </div>
        <div className="text-[10px] tracking-widest text-[var(--text-dim)]">
          AGENTIC OPERATING SYSTEM
        </div>
        <div className="mt-2 flex items-center gap-1.5 text-[10px]">
          <span
            className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-emerald-400" : "bg-red-400"}`}
          />
          <span className="text-[var(--text-dim)]">
            {connected ? "EVENT STREAM LIVE" : "GATEWAY OFFLINE"}
          </span>
        </div>
      </div>
      {SECTIONS.map((section) =>
        section.href ? (
          <Link
            key={section.label}
            href={section.href}
            className={`rounded px-2 py-1.5 text-xs transition-colors ${
              pathname === section.href
                ? "bg-sky-500/15 text-sky-300"
                : "text-[var(--text-dim)] hover:bg-sky-500/8 hover:text-[var(--text)]"
            }`}
          >
            {section.label}
          </Link>
        ) : (
          <div
            key={section.label}
            title={section.pending}
            className="cursor-not-allowed rounded px-2 py-1.5 text-xs text-[var(--text-dim)] opacity-40"
          >
            {section.label}
            <span className="ml-1 text-[9px]">◦ pending</span>
          </div>
        ),
      )}
    </nav>
  );
}
