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
  type StructuredData,
} from "@/lib/api";

type ConnectionStatus = "loading" | "connected" | "error";

const LOADING_STEPS = [
  "Remembering your entry…",
  "Finding connections…",
  "Detecting patterns…",
];

function formatSpend(value: number | undefined): string | undefined {
  if (value === undefined || value === null) return undefined;
  return `$${value}`;
}

function SignalCard({
  label,
  value,
  icon,
}: {
  label: string;
  value: string | undefined;
  icon: string;
}) {
  if (!value || value === "unknown" || value === "none") return null;
  return (
    <div className="glass-panel rounded-2xl bg-zinc-900/60 p-4 backdrop-blur-md border border-zinc-800/80 transition hover:border-emerald-500/30">
      <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/10 text-sm text-emerald-400/90 ring-1 ring-cyan-500/10">
        {icon}
      </div>
      <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">
        {label}
      </p>
      <p className="mt-1 text-base font-medium capitalize text-zinc-100">
        {value}
      </p>
    </div>
  );
}

function MemoryStatus({
  status,
  dbCheck,
  errorMessage,
}: {
  status: ConnectionStatus;
  dbCheck: DatabaseCheck | null;
  errorMessage: string | null;
}) {
  const connected = status === "connected";
  const dotClass = connected
    ? "bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.7)] animate-pulse-glow"
    : status === "error"
      ? "bg-red-400/90"
      : "bg-amber-400/90 animate-pulse";

  const headline = connected
    ? "Memory system connected"
    : status === "error"
      ? "Memory system offline"
      : "Connecting to memory…";

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${dotClass}`} />
        <span
          className={`text-sm ${connected ? "font-medium text-emerald-400" : "text-zinc-300"}`}
        >
          {headline}
        </span>
      </div>
      {connected && dbCheck && (
        <span className="rounded-full border border-cyan-500/25 bg-cyan-950/30 px-3 py-1 text-xs text-cyan-300/90 shadow-[0_0_12px_rgba(6,182,212,0.12)]">
          CockroachDB memory · {dbCheck.diary_entries_count} memories ·{" "}
          {dbCheck.life_vector_memory_count} vectors
        </span>
      )}
      {status === "error" && errorMessage && (
        <span className="text-xs text-red-400/90">{errorMessage}</span>
      )}
    </div>
  );
}

function LoadingState({ step }: { step: number }) {
  return (
    <div className="animate-fade-in mt-6 rounded-2xl border border-emerald-500/20 bg-emerald-500/5 px-5 py-4 shadow-[0_0_20px_rgba(16,185,129,0.06)]">
      <div className="flex items-center gap-3">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-emerald-500/20 border-t-emerald-400" />
        <p className="text-sm text-emerald-300/90">{LOADING_STEPS[step]}</p>
      </div>
      <div className="mt-3 flex gap-2">
        {LOADING_STEPS.map((label, i) => (
          <span
            key={label}
            className={`rounded-full px-2.5 py-0.5 text-[10px] transition ${
              i === step
                ? "bg-emerald-500/15 text-emerald-300 ring-1 ring-cyan-500/20"
                : i < step
                  ? "text-zinc-600"
                  : "text-zinc-700"
            }`}
          >
            {label.replace("…", "")}
          </span>
        ))}
      </div>
    </div>
  );
}

function PatternModal({
  open,
  onClose,
  causeEffect,
  agentMessage,
  suggestedAlternative,
  ethicalNote,
  agentDecision,
  closestEntry,
}: {
  open: boolean;
  onClose: () => void;
  causeEffect?: string;
  agentMessage?: string;
  suggestedAlternative?: string;
  ethicalNote?: string;
  agentDecision?: string | null;
  closestEntry?: { detected_emotion?: string; main_event?: string; created_at?: string | null };
}) {
  if (!open) return null;

  const actionText = agentMessage || suggestedAlternative;

  return (
    <div
      className="animate-fade-in fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="pattern-modal-title"
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
        aria-label="Close insight"
      />
      <div className="animate-fade-up glass-panel relative w-full max-w-lg rounded-3xl p-6 shadow-2xl shadow-black/40 sm:p-8">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-teal-400/80">
              Anima noticed a pattern
            </p>
            {agentDecision && (
              <p className="mt-2 text-xs font-medium text-amber-200/90">
                {agentDecision}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-2 py-1 text-zinc-500 transition hover:bg-zinc-800 hover:text-zinc-300"
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>

        {causeEffect && (
          <blockquote className="border-l-2 border-teal-500/40 pl-4 text-base leading-relaxed text-zinc-200">
            {causeEffect}
          </blockquote>
        )}

        {actionText && (
          <div className="mt-6 rounded-2xl border border-teal-500/15 bg-teal-500/5 p-4">
            <p className="text-[11px] font-medium uppercase tracking-wider text-teal-400/70">
              Suggested action
            </p>
            <p className="mt-2 text-sm leading-relaxed text-zinc-100">
              {actionText}
            </p>
          </div>
        )}

        {closestEntry && (
          <p className="mt-4 text-xs text-zinc-500">
            Based on a similar memory from your past
            {closestEntry.detected_emotion || closestEntry.main_event
              ? ` (${[closestEntry.detected_emotion, closestEntry.main_event].filter(Boolean).join(" · ")})`
              : ""}
            .
          </p>
        )}

        {ethicalNote && (
          <p className="mt-4 text-xs italic text-zinc-500">{ethicalNote}</p>
        )}

        <button
          type="button"
          onClick={onClose}
          className="mt-6 w-full rounded-xl border border-zinc-700/80 bg-zinc-900/80 py-2.5 text-sm text-zinc-300 transition hover:border-zinc-600 hover:text-white"
        >
          Continue
        </button>
      </div>
    </div>
  );
}

function buildSignals(data: StructuredData | undefined) {
  return [
    { label: "Emotion", value: data?.detected_emotion, icon: "◐" },
    {
      label: "People",
      value: data?.people_involved,
      icon: "◎",
    },
    { label: "Activity", value: data?.main_event, icon: "◈" },
    {
      label: "Spending",
      value: formatSpend(data?.total_spend),
      icon: "◆",
    },
    { label: "Weather", value: data?.weather_condition, icon: "◌" },
    { label: "Meal", value: data?.main_meal, icon: "◇" },
  ];
}

export default function Home() {
  const [userId, setUserId] = useState("");
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ProcessResponse | null>(null);
  const [showPatternModal, setShowPatternModal] = useState(false);

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

  useEffect(() => {
    if (!loading) {
      setLoadingStep(0);
      return;
    }
    const id = window.setInterval(() => {
      setLoadingStep((s) => (s + 1) % LOADING_STEPS.length);
    }, 2200);
    return () => window.clearInterval(id);
  }, [loading]);

  const resetUser = useCallback(() => {
    if (
      !window.confirm(
        "Reset your private memory profile? Past patterns will no longer be linked to this session.",
      )
    ) {
      return;
    }
    const next = createUserId();
    localStorage.setItem(USER_ID_STORAGE_KEY, next);
    setUserId(next);
    setResult(null);
    setError(null);
    setShowPatternModal(false);
  }, []);

  const submitNote = async () => {
    if (!note.trim() || !userId) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setShowPatternModal(false);

    try {
      const payload = await processDiaryNote(note.trim(), userId);
      setResult(payload);
      if (payload.database_check) {
        setHealthCheck(payload.database_check);
        setConnectionStatus("connected");
      }
      if (payload.pattern_insight?.has_pattern === true) {
        setShowPatternModal(true);
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
  const hasPattern = insight?.has_pattern === true;
  const agentDecision =
    insight?.agent_decision ?? suggestion?.agent_decision ?? null;
  const closestSimilar = insight?.similar_entries?.[0];
  const similarCount = insight?.similar_entries?.length ?? 0;
  const signals = buildSignals(structured);

  return (
    <div className="ambient-bg min-h-full bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-teal-900/20 via-[#09090b] to-[#09090b] text-zinc-100">
      <PatternModal
        open={showPatternModal && hasPattern}
        onClose={() => setShowPatternModal(false)}
        causeEffect={suggestion?.cause_effect}
        agentMessage={suggestion?.agent_message}
        suggestedAlternative={suggestion?.suggested_alternative}
        ethicalNote={suggestion?.ethical_note}
        agentDecision={agentDecision}
        closestEntry={closestSimilar}
      />

      <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6 sm:py-14 lg:py-16">
        {/* Header */}
        <header className="animate-fade-up mb-10 sm:mb-12">
          <img
            src="/banner.png"
            alt="Anima banner"
            className="mb-6 w-full rounded-2xl border border-emerald-500/20 object-cover shadow-[0_0_24px_rgba(16,185,129,0.12)] max-h-36 sm:max-h-44"
          />
          <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="flex items-center gap-3">
                <img
                  src="/logo.png"
                  alt="Anima Logo"
                  className="h-10 w-10 rounded-xl object-contain border border-emerald-500/30 shadow-[0_0_15px_rgba(16,185,129,0.3)]"
                />
                <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-emerald-400">
                  Anima
                </p>
              </div>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">
                Your memories, connected.
              </h1>
              <p className="mt-3 max-w-md text-base leading-relaxed text-zinc-400">
                An AI diary that remembers your experiences, finds connections,
                and notices recurring patterns.
              </p>
              <div className="mt-6">
                <MemoryStatus
                  status={connectionStatus}
                  dbCheck={healthCheck}
                  errorMessage={healthError}
                />
              </div>
            </div>

            <div className="glass-panel shrink-0 rounded-2xl bg-zinc-900/60 px-4 py-3 backdrop-blur-md border border-zinc-800/80 sm:min-w-[200px] hover:border-emerald-500/30">
              <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">
                Your private memory
              </p>
              <p className="mt-1 text-sm text-zinc-300">Memory profile active</p>
              <button
                type="button"
                onClick={resetUser}
                className="mt-3 text-xs text-zinc-500 underline-offset-2 transition hover:text-emerald-400 hover:underline"
              >
                Reset memory
              </button>
            </div>
          </div>
        </header>

        {/* Diary input — centerpiece */}
        <section className="animate-fade-up glass-panel mb-10 rounded-3xl bg-zinc-900/60 p-6 shadow-xl shadow-black/30 backdrop-blur-md border border-zinc-800/80 sm:p-8 hover:border-emerald-500/30">
          <h2 className="text-xl font-medium text-white">
            What&apos;s on your mind?
          </h2>
          <p className="mt-2 text-sm text-zinc-400">
            Write naturally. Anima will remember the important details.
          </p>

          <textarea
            id="diary-note"
            rows={7}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={`"Today I felt stressed while working on my project. I spent €20 on food, and talking with a friend helped me feel better."`}
            disabled={loading}
            className="mt-6 w-full resize-y rounded-2xl border border-zinc-800/80 bg-zinc-950/50 px-4 py-4 text-[15px] leading-relaxed text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-500/40 focus:outline-none focus:ring-2 focus:ring-emerald-500/15 disabled:opacity-60"
          />

          <div className="mt-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <button
              type="button"
              onClick={submitNote}
              disabled={loading || !note.trim() || connectionStatus === "error"}
              className="inline-flex items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-emerald-500 to-teal-400 px-6 py-3 text-sm font-bold text-black shadow-lg shadow-emerald-900/25 transition-all hover:shadow-[0_0_25px_rgba(16,185,129,0.4)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {loading ? (
                <>
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-black/20 border-t-black" />
                  Remember & Analyze
                </>
              ) : (
                "Remember & Analyze"
              )}
            </button>
            {connectionStatus === "error" && (
              <button
                type="button"
                onClick={runHealthCheck}
                className="text-xs text-zinc-500 underline-offset-2 hover:text-emerald-400 hover:underline"
              >
                Retry connection
              </button>
            )}
          </div>

          {loading && <LoadingState step={loadingStep} />}
        </section>

        {error && (
          <div
            role="alert"
            className="animate-fade-in mb-8 rounded-2xl border border-red-900/40 bg-red-950/20 px-5 py-4 text-sm text-red-300"
          >
            {error}
          </div>
        )}

        {result && (
          <div className="animate-fade-up space-y-8">
            {/* 1. What Anima understood */}
            <section>
              <h3 className="mb-4 text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">
                What Anima understood
              </h3>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {signals.map((s) => (
                  <SignalCard
                    key={s.label}
                    label={s.label}
                    value={s.value}
                    icon={s.icon}
                  />
                ))}
              </div>
            </section>

            {/* 2. What Anima remembered */}
            <section className="glass-panel rounded-2xl bg-zinc-900/60 p-5 backdrop-blur-md border border-zinc-800/80 sm:p-6 hover:border-emerald-500/30">
              <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">
                What Anima remembered
              </h3>
              <p className="mt-3 text-sm leading-relaxed text-zinc-300">
                {result.message ??
                  "Your entry was saved to persistent memory and indexed for future connections."}
              </p>
              {similarCount > 0 && (
                <p className="mt-2 text-sm text-zinc-500">
                  Found {similarCount} related{" "}
                  {similarCount === 1 ? "memory" : "memories"} in your history.
                </p>
              )}
            </section>

            {/* 3–4. Pattern + suggested action */}
            <section
              className={`rounded-2xl border p-5 backdrop-blur-md sm:p-6 ${
                hasPattern
                  ? "border-emerald-500/30 bg-gradient-to-br from-emerald-950/35 to-zinc-900/50 shadow-[0_0_30px_rgba(16,185,129,0.08)]"
                  : "glass-panel bg-zinc-900/60 border-zinc-800/80 hover:border-emerald-500/30"
              }`}
            >
              <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">
                {hasPattern ? "Pattern detected" : "Pattern status"}
              </h3>

              {hasPattern ? (
                <div className="mt-4 space-y-4">
                  {agentDecision && (
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/25 bg-amber-950/30 px-3 py-1.5 text-xs font-medium text-amber-200/90">
                      {agentDecision}
                    </span>
                  )}
                  {suggestion?.cause_effect && (
                    <p className="text-sm leading-relaxed text-zinc-300">
                      {suggestion.cause_effect}
                    </p>
                  )}
                  {(suggestion?.agent_message ||
                    suggestion?.suggested_alternative) && (
                    <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 p-4 shadow-[0_0_16px_rgba(16,185,129,0.06)]">
                      <p className="text-[11px] font-medium uppercase tracking-wider text-emerald-400/80">
                        Suggested action
                      </p>
                      <p className="mt-2 text-base font-medium text-white">
                        {suggestion.agent_message ||
                          suggestion.suggested_alternative}
                      </p>
                    </div>
                  )}
                  {suggestion?.ethical_note && (
                    <p className="text-xs italic text-zinc-500">
                      {suggestion.ethical_note}
                    </p>
                  )}
                </div>
              ) : (
                <div className="mt-4 space-y-2">
                  <p className="text-sm font-medium text-zinc-300">
                    No recurring pattern found yet.
                  </p>
                  <p className="text-sm text-zinc-500">
                    {insight?.summary ??
                      "Anima will keep learning from future memories."}
                  </p>
                </div>
              )}
            </section>

            {/* 5. Technical memory — for judges */}
            <section className="border-t border-zinc-800/80 pt-8">
              <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">
                How Anima remembers
              </h3>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {[
                  { title: "Persistent memory", value: "CockroachDB" },
                  {
                    title: "Semantic memory",
                    value: `${result.vector_length ?? 1536}-dimensional embeddings`,
                  },
                  {
                    title: "Vector retrieval",
                    value: "CockroachDB Distributed Vector Indexing",
                  },
                  { title: "AI reasoning", value: "Amazon Bedrock" },
                  { title: "Execution", value: "AWS Lambda" },
                ].map((item) => (
                  <div
                    key={item.title}
                    className="rounded-xl border border-zinc-800/60 bg-zinc-950/50 px-4 py-3 transition hover:border-cyan-500/20"
                  >
                    <p className="text-[10px] uppercase tracking-wider text-zinc-600">
                      {item.title}
                    </p>
                    <p className="mt-1 text-sm text-zinc-400">{item.value}</p>
                  </div>
                ))}
              </div>

              <details className="mt-6 rounded-xl border border-zinc-800/60 bg-zinc-950/30 px-4 py-3">
                <summary className="cursor-pointer text-xs font-medium text-zinc-500 hover:text-zinc-400">
                  Memory diagnostics
                </summary>
                <dl className="mt-4 space-y-2 font-mono text-[11px] text-zinc-600">
                  {healthCheck && (
                    <>
                      <div className="flex justify-between gap-4">
                        <dt>database ok</dt>
                        <dd>{healthCheck.ok}</dd>
                      </div>
                      <div className="flex justify-between gap-4">
                        <dt>diary_entries</dt>
                        <dd>{healthCheck.diary_entries_count}</dd>
                      </div>
                      <div className="flex justify-between gap-4">
                        <dt>vectors</dt>
                        <dd>{healthCheck.life_vector_memory_count}</dd>
                      </div>
                    </>
                  )}
                  {result.entry_id && (
                    <div className="flex justify-between gap-4">
                      <dt>entry_id</dt>
                      <dd className="truncate text-right">{result.entry_id}</dd>
                    </div>
                  )}
                  {result.user_id && (
                    <div className="flex justify-between gap-4">
                      <dt>user_id</dt>
                      <dd className="truncate text-right">{result.user_id}</dd>
                    </div>
                  )}
                  {insight?.closest_distance != null && (
                    <div className="flex justify-between gap-4">
                      <dt>closest_distance</dt>
                      <dd>{insight.closest_distance.toFixed(4)}</dd>
                    </div>
                  )}
                  <div className="flex justify-between gap-4">
                    <dt>similar_count</dt>
                    <dd>{similarCount}</dd>
                  </div>
                  {result.vector_length != null && (
                    <div className="flex justify-between gap-4">
                      <dt>vector_length</dt>
                      <dd>{result.vector_length}</dd>
                    </div>
                  )}
                </dl>

                {(insight?.similar_entries?.length ?? 0) > 0 && (
                  <ul className="mt-4 space-y-2 border-t border-zinc-800/60 pt-4">
                    {insight?.similar_entries?.map((entry) => (
                      <li
                        key={entry.entry_id}
                        className="rounded-lg bg-zinc-900/50 px-3 py-2 text-[11px] text-zinc-500"
                      >
                        d={entry.distance?.toFixed(4) ?? "—"} ·{" "}
                        {entry.detected_emotion} · {entry.main_event}
                      </li>
                    ))}
                  </ul>
                )}
              </details>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
