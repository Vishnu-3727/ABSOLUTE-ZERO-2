"use client";
// The command bar: `intent :: goal1, goal2` runs a real request through
// the OS. Without "::" the whole line is the intent.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";

export function CommandBar() {
  const [line, setLine] = useState("");
  const queryClient = useQueryClient();
  const run = useMutation({
    mutationFn: (input: string) => {
      const [intent, goalPart] = input.split("::");
      const goals = goalPart
        ? goalPart.split(",").map((g) => g.trim()).filter(Boolean)
        : ["analyze"];
      return api.submit(intent.trim(), goals);
    },
    onSuccess: () => {
      setLine("");
      queryClient.invalidateQueries();
    },
  });

  return (
    <div className="panel flex items-center gap-3 px-4 py-2.5">
      <span className="mono glow text-xs text-sky-300">AZ-OS ›</span>
      <input
        value={line}
        onChange={(e) => setLine(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && line.trim() && run.mutate(line)}
        placeholder="run a request…   e.g.  fix the parser bug :: analyze code, build fix, test suite, report results"
        className="mono flex-1 bg-transparent text-xs text-[var(--text)] outline-none placeholder:text-[var(--text-dim)]/50"
        aria-label="command input"
      />
      <button
        onClick={() => line.trim() && run.mutate(line)}
        disabled={run.isPending}
        className="rounded border border-sky-400/40 bg-sky-500/15 px-4 py-1 text-[10px] font-semibold tracking-widest text-sky-300 hover:bg-sky-500/25 disabled:opacity-40"
      >
        {run.isPending ? "RUNNING…" : "EXECUTE"}
      </button>
      {run.isError && (
        <span className="text-[10px] text-red-400">{String(run.error)}</span>
      )}
    </div>
  );
}
