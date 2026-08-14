"use client";

import { useCallback, useEffect, useState } from "react";

const LAMBDA_URL =
  "https://dpchzhzc7xvmdvqsgzn4irzqau0auolr.lambda-url.us-east-1.on.aws/";
const STORAGE_KEY = "synap_user_id";

type StructuredData = {
  detected_emotion?: string;
  main_meal?: string;
  total_spend?: number;
  main_event?: string;
  people_involved?: string;
  weather_condition?: string;
};

type AgentSuggestion = {
  action_triggered?: boolean;
  cause_effect?: string;
  agent_message?: string;
  suggested_alternative?: string;
  ethical_note?: string;
};

type PatternInsight = {
  has_pattern?: boolean;
  summary?: string;
  closest_distance?: number | null;
  agent_suggestion?: AgentSuggestion | null;
};

type ApiPayload = {
  message?: string;
  error?: string;
  user_id?: string;
  entry_id?: string;
  structured_data?: StructuredData;
  pattern_insight?: PatternInsight;
};

function createUserId(): string {
  return `usr_${crypto.randomUUID()}`;
}

function getOrCreateUserId(): string {
  const existing = localStorage.getItem(STORAGE_KEY);
  if (existing) return existing;
  const next = createUserId();
  localStorage.setItem(STORAGE_KEY, next);
  return next;
}

function Badge({
  label,
  value,
  accent,
}: {
  label: string;
  value: string | number | undefined;
  accent?: string;
}) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${accent ?? "border-zinc-700 bg-zinc-800/80 text-zinc-200"}`}
    >
      <span className="text-zinc-500">{label}</span>
      <span>{value}</span>
    </span>
  );
}

export default function Home() {
  const [userId, setUserId] = useState<string>("");
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ApiPayload | null>(null);

  useEffect(() => {
    setUserId(getOrCreateUserId());
  }, []);

  const resetUser = useCallback(() => {
    const next = createUserId();
    localStorage.setItem(STORAGE_KEY, next);
    setUserId(next);
    setResult(null);
    setError(null);
  }, []);

  const submitNote = async () => {
    if (!note.trim() || !userId) return;
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await fetch(LAMBDA_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: note.trim(), user_id: userId }),
      });

      const raw = await res.json();
      const payload: ApiPayload =
        typeof raw.body === "string" ? JSON.parse(raw.body) : raw;

      if (!res.ok || payload.error) {
        throw new Error(payload.error ?? `Request failed (${res.status})`);
      }

      setResult(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unexpected error");
    } finally {
      setLoading(false);
    }
  };

  const structured = result?.structured_data;
  const insight = result?.pattern_insight;
  const suggestion = insight?.agent_suggestion;

  return (
    <div className="min-h-full bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8">
        {/* Header */}
        <header className="mb-10 border-b border-zinc-800 pb-8">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-[0.2em] text-emerald-400">
                Synap
              </p>
              <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
                Autonomous Agentic Memory
              </h1>
              <p className="mt-2 max-w-xl text-sm text-zinc-400">
                Pattern detection powered by{" "}
                <span className="text-zinc-300">CockroachDB</span> &{" "}
                <span className="text-zinc-300">AWS Bedrock</span>
              </p>
            </div>

            <div className="flex flex-col items-start gap-2 sm:items-end">
              <p className="text-[10px] uppercase tracking-wider text-zinc-500">
                Memory scope
              </p>
              <code className="rounded-lg border border-zinc-800 bg-zinc-900 px-2 py-1 font-mono text-[11px] text-zinc-400">
                {userId || "…"}
              </code>
              <button
                type="button"
                onClick={resetUser}
                className="text-xs text-zinc-500 underline-offset-2 transition hover:text-emerald-400 hover:underline"
              >
                New User / Reset Memory
              </button>
            </div>
          </div>
        </header>

        {/* Diary input */}
        <section className="mb-8 rounded-2xl border border-zinc-800 bg-zinc-900/50 p-6 shadow-xl shadow-black/20">
          <label
            htmlFor="diary-note"
            className="mb-3 block text-sm font-medium text-zinc-300"
          >
            Diary entry
          </label>
          <textarea
            id="diary-note"
            rows={6}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Today I felt sad, my mom visited, it was sunny, ate pizza, spent $30 at the pharmacy…"
            className="w-full resize-y rounded-xl border border-zinc-700 bg-zinc-950 px-4 py-3 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-500/60 focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
          />
          <div className="mt-4 flex items-center gap-4">
            <button
              type="button"
              onClick={submitNote}
              disabled={loading || !note.trim()}
              className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {loading ? (
                <>
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                  Analyzing…
                </>
              ) : (
                "Analyze & Detect Patterns"
              )}
            </button>
            {loading && (
              <span className="text-xs text-zinc-500">
                Bedrock extract → embed → CockroachDB recall
              </span>
            )}
          </div>
        </section>

        {/* Error */}
        {error && (
          <div className="mb-8 rounded-xl border border-red-900/50 bg-red-950/30 px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        )}

        {/* Results */}
        {result && (
          <section className="space-y-6">
            <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6">
              <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                Extracted signals
              </h2>
              <div className="flex flex-wrap gap-2">
                <Badge
                  label="Emotion"
                  value={structured?.detected_emotion}
                  accent="border-violet-800/60 bg-violet-950/40 text-violet-200"
                />
                <Badge
                  label="Meal"
                  value={structured?.main_meal}
                  accent="border-amber-800/60 bg-amber-950/40 text-amber-200"
                />
                <Badge
                  label="Spend"
                  value={
                    structured?.total_spend !== undefined
                      ? `$${structured.total_spend}`
                      : undefined
                  }
                  accent="border-sky-800/60 bg-sky-950/40 text-sky-200"
                />
                <Badge
                  label="Event"
                  value={structured?.main_event}
                  accent="border-zinc-700 bg-zinc-800/80 text-zinc-200"
                />
                <Badge
                  label="Weather"
                  value={structured?.weather_condition}
                  accent="border-cyan-800/60 bg-cyan-950/40 text-cyan-200"
                />
                {structured?.people_involved &&
                  structured.people_involved !== "none" && (
                    <Badge
                      label="People"
                      value={structured.people_involved}
                      accent="border-pink-800/60 bg-pink-950/40 text-pink-200"
                    />
                  )}
              </div>
              {result.entry_id && (
                <p className="mt-4 font-mono text-[10px] text-zinc-600">
                  entry_id: {result.entry_id}
                </p>
              )}
            </div>

            {/* Pattern insight */}
            <div
              className={`rounded-2xl border p-6 ${
                insight?.has_pattern
                  ? "border-emerald-800/50 bg-gradient-to-br from-emerald-950/40 to-zinc-900/60 shadow-lg shadow-emerald-950/20"
                  : "border-zinc-800 bg-zinc-900/40"
              }`}
            >
              <div className="mb-4 flex items-center justify-between gap-4">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-300">
                  Pattern Insight / Proactive Agent
                </h2>
                {insight?.closest_distance != null && (
                  <span className="rounded-full border border-zinc-700 bg-zinc-950 px-3 py-1 font-mono text-xs text-zinc-400">
                    distance: {insight.closest_distance.toFixed(4)}
                  </span>
                )}
              </div>

              {insight?.has_pattern && suggestion ? (
                <div className="space-y-4">
                  <div>
                    <p className="mb-1 text-xs font-medium text-emerald-400/80">
                      Cause → effect
                    </p>
                    <p className="text-sm leading-relaxed text-zinc-300">
                      {suggestion.cause_effect}
                    </p>
                  </div>
                  <div>
                    <p className="mb-1 text-xs font-medium text-emerald-400/80">
                      Agent message
                    </p>
                    <p className="text-base font-medium leading-relaxed text-white">
                      {suggestion.agent_message}
                    </p>
                  </div>
                  <div>
                    <p className="mb-1 text-xs font-medium text-emerald-400/80">
                      Suggested alternative
                    </p>
                    <p className="text-sm leading-relaxed text-zinc-300">
                      {suggestion.suggested_alternative}
                    </p>
                  </div>
                  {suggestion.ethical_note && (
                    <p className="text-xs italic text-zinc-500">
                      {suggestion.ethical_note}
                    </p>
                  )}
                </div>
              ) : (
                <p className="text-sm text-zinc-400">
                  {insight?.summary ??
                    "No strong pattern yet. Add another similar entry to build memory."}
                </p>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
