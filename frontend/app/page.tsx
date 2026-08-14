"use client";

import { useCallback, useEffect, useState } from "react";

import {
  createUserId,
  fetchHealth,
  getOrCreateUserId,
  LambdaApiError,
  processDiaryNote,
  USER_ID_STORAGE_KEY,
  type DatabaseCheck,
  type ProcessResponse,
} from "@/lib/api";

type ConnectionStatus = "loading" | "connected" | "error";

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

function ConnectionIndicator({
  status,
  dbCheck,
  errorMessage,
}: {
  status: ConnectionStatus;
  dbCheck: DatabaseCheck | null;
  errorMessage: string | null;
}) {
  const dotClass =
    status === "connected"
      ? "bg-emerald-400 shadow-emerald-400/50"
      : status === "error"
        ? "bg-red-400 shadow-red-400/50"
        : "bg-amber-400 animate-pulse shadow-amber-400/50";

  const label =
    status === "connected"
      ? "CockroachDB connected"
      : status === "error"
        ? "Connection failed"
        : "Checking connection…";

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 px-4 py-3">
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full shadow-sm ${dotClass}`} />
        <span className="text-xs font-medium text-zinc-300">{label}</span>
      </div>
      {status === "connected" && dbCheck && (
        <p className="mt-2 font-mono text-[11px] text-zinc-500">
          ok={dbCheck.ok} · diary_entries={dbCheck.diary_entries_count} ·
          vectors={dbCheck.life_vector_memory_count}
        </p>
      )}
      {status === "error" && errorMessage && (
        <p className="mt-2 text-xs text-red-400">{errorMessage}</p>
      )}
    </div>
  );
}

export default function Home() {
  const [userId, setUserId] = useState("");
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ProcessResponse | null>(null);

  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("loading");
  const [healthCheck, setHealthCheck] = useState<DatabaseCheck | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const runHealthCheck = useCallback(async () => {
    setConnectionStatus("loading");
    setHealthError(null);
    try {
      const data = await fetchHealth();
      if (data.database_check?.ok === 1) {
        setHealthCheck(data.database_check);
        setConnectionStatus("connected");
      } else {
        throw new LambdaApiError("Database check did not return ok=1", 500);
      }
    } catch (err) {
      setHealthCheck(null);
      setConnectionStatus("error");
      setHealthError(
        err instanceof LambdaApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Health check failed",
      );
    }
  }, []);

  useEffect(() => {
    setUserId(getOrCreateUserId());
    runHealthCheck();
  }, [runHealthCheck]);

  const resetUser = useCallback(() => {
    const next = createUserId();
    localStorage.setItem(USER_ID_STORAGE_KEY, next);
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
      const payload = await processDiaryNote(note.trim(), userId);
      setResult(payload);
      if (payload.database_check) {
        setHealthCheck(payload.database_check);
        setConnectionStatus("connected");
      }
    } catch (err) {
      setError(
        err instanceof LambdaApiError
          ? `[${err.status}] ${err.message}`
          : err instanceof Error
            ? err.message
            : "Unexpected error",
      );
    } finally {
      setLoading(false);
    }
  };

  const structured = result?.structured_data;
  const insight = result?.pattern_insight;
  const suggestion = insight?.agent_suggestion;
  const showProactiveCard =
    insight?.has_pattern === true && suggestion != null;

  return (
    <div className="min-h-full bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8">
        <header className="mb-8 border-b border-zinc-800 pb-8">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
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

            <div className="flex w-full flex-col gap-3 sm:max-w-xs">
              <ConnectionIndicator
                status={connectionStatus}
                dbCheck={healthCheck}
                errorMessage={healthError}
              />
              <button
                type="button"
                onClick={runHealthCheck}
                disabled={connectionStatus === "loading"}
                className="text-left text-xs text-zinc-500 underline-offset-2 hover:text-emerald-400 hover:underline disabled:opacity-50"
              >
                Retry connection check
              </button>
              <div>
                <p className="text-[10px] uppercase tracking-wider text-zinc-500">
                  Memory scope (user_id)
                </p>
                <code className="mt-1 block truncate rounded-lg border border-zinc-800 bg-zinc-900 px-2 py-1 font-mono text-[11px] text-zinc-400">
                  {userId || "…"}
                </code>
                <button
                  type="button"
                  onClick={resetUser}
                  className="mt-2 text-xs text-zinc-500 underline-offset-2 hover:text-emerald-400 hover:underline"
                >
                  New User / Reset Memory
                </button>
              </div>
            </div>
          </div>
        </header>

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
            disabled={loading}
            className="w-full resize-y rounded-xl border border-zinc-700 bg-zinc-950 px-4 py-3 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-500/60 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 disabled:opacity-60"
          />
          <div className="mt-4 flex flex-wrap items-center gap-4">
            <button
              type="button"
              onClick={submitNote}
              disabled={loading || !note.trim() || connectionStatus === "error"}
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
                Bedrock extract → Titan embed → CockroachDB vector recall
              </span>
            )}
          </div>
        </section>

        {error && (
          <div
            role="alert"
            className="mb-8 rounded-xl border border-red-900/50 bg-red-950/30 px-4 py-3 text-sm text-red-300"
          >
            {error}
          </div>
        )}

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
              <div className="mt-4 space-y-1 font-mono text-[10px] text-zinc-600">
                {result.entry_id && <p>entry_id: {result.entry_id}</p>}
                {result.vector_length != null && (
                  <p>vector_length: {result.vector_length}</p>
                )}
                {result.user_id && <p>user_id: {result.user_id}</p>}
              </div>
            </div>

            <div
              className={`rounded-2xl border p-6 ${
                showProactiveCard
                  ? "border-emerald-800/50 bg-gradient-to-br from-emerald-950/40 to-zinc-900/60 shadow-lg shadow-emerald-950/20"
                  : "border-zinc-800 bg-zinc-900/40"
              }`}
            >
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-300">
                  Pattern insight
                </h2>
                {insight?.closest_distance != null && (
                  <span className="rounded-full border border-zinc-700 bg-zinc-950 px-3 py-1 font-mono text-xs text-zinc-400">
                    closest_distance: {insight.closest_distance.toFixed(4)}
                  </span>
                )}
              </div>

              {showProactiveCard ? (
                <div className="space-y-5">
                  <p className="text-xs font-medium uppercase tracking-wide text-emerald-400/90">
                    Proactive agent — optional suggestion
                  </p>
                  {suggestion.cause_effect && (
                    <div>
                      <p className="mb-1 text-xs text-zinc-500">Cause → effect</p>
                      <p className="text-sm leading-relaxed text-zinc-300">
                        {suggestion.cause_effect}
                      </p>
                    </div>
                  )}
                  {suggestion.agent_message && (
                    <div>
                      <p className="mb-1 text-xs text-zinc-500">Agent message</p>
                      <p className="text-base font-medium leading-relaxed text-white">
                        {suggestion.agent_message}
                      </p>
                    </div>
                  )}
                  {suggestion.suggested_alternative && (
                    <div>
                      <p className="mb-1 text-xs text-zinc-500">
                        Suggested alternative
                      </p>
                      <p className="text-sm leading-relaxed text-zinc-300">
                        {suggestion.suggested_alternative}
                      </p>
                    </div>
                  )}
                  {suggestion.ethical_note && (
                    <p className="rounded-lg border border-zinc-700/80 bg-zinc-950/50 px-3 py-2 text-xs italic text-zinc-400">
                      {suggestion.ethical_note}
                    </p>
                  )}
                </div>
              ) : (
                <p className="text-sm leading-relaxed text-zinc-400">
                  {insight?.summary ??
                    "No pattern insight returned. Try another entry."}
                </p>
              )}

              {(insight?.similar_entries?.length ?? 0) > 0 && (
                <details className="mt-6 border-t border-zinc-800 pt-4">
                  <summary className="cursor-pointer text-xs text-zinc-500 hover:text-zinc-400">
                    Similar past entries ({insight?.similar_entries?.length})
                  </summary>
                  <ul className="mt-3 space-y-2">
                    {insight?.similar_entries?.map((entry) => (
                      <li
                        key={entry.entry_id}
                        className="rounded-lg border border-zinc-800 bg-zinc-950/50 px-3 py-2 text-xs text-zinc-400"
                      >
                        <span className="font-mono text-zinc-500">
                          d={entry.distance?.toFixed(4) ?? "—"}
                        </span>
                        {" · "}
                        {entry.detected_emotion} · {entry.main_event}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
