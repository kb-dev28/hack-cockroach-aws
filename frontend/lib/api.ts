/** Lambda Function URL — matches lambda/utils.py DEFAULT_USER_ID fallback on server. */
export const LAMBDA_URL =
  "https://dpchzhzc7xvmdvqsgzn4irzqau0auolr.lambda-url.us-east-1.on.aws/";
  

export const USER_ID_STORAGE_KEY = "synap_user_id";

export type DatabaseCheck = {
  ok: number;
  diary_entries_count: number;
  life_vector_memory_count: number;
};

export type HealthResponse = {
  message?: string;
  database_check?: DatabaseCheck;
  error?: string;
};

export type StructuredData = {
  detected_emotion?: string;
  main_meal?: string;
  total_spend?: number;
  main_event?: string;
  people_involved?: string;
  weather_condition?: string;
};

export type PatternSignal = {
  type: string;
  detail: string;
};

export type AgentSuggestion = {
  action_triggered?: boolean;
  cause_effect?: string;
  signals?: PatternSignal[];
  suggested_alternative?: string;
  supporting_alternatives?: string[];
  agent_message?: string;
  ethical_note?: string;
};

export type SimilarEntry = {
  entry_id?: string;
  user_note?: string;
  detected_emotion?: string;
  main_meal?: string;
  total_spend?: number;
  main_event?: string;
  people_involved?: string;
  weather_condition?: string;
  created_at?: string | null;
  distance?: number | null;
};

export type PatternInsight = {
  has_pattern?: boolean;
  summary?: string;
  current?: StructuredData;
  similar_entries?: SimilarEntry[];
  closest_distance?: number | null;
  agent_suggestion?: AgentSuggestion | null;
};

/** 200 response from process mode (lambda_handler merges database_check + process_diary_note). */
export type ProcessResponse = {
  message?: string;
  error?: string;
  database_check?: DatabaseCheck;
  user_id?: string;
  entry_id?: string;
  structured_data?: StructuredData;
  vector_length?: number;
  pattern_insight?: PatternInsight;
};

/** Function URL returns JSON body directly; direct invoke / API GW may wrap in { body: string }. */
export function parseLambdaJson<T>(raw: unknown): T {
  if (raw && typeof raw === "object" && "body" in raw) {
    const body = (raw as { body?: unknown }).body;
    if (typeof body === "string") {
      return JSON.parse(body) as T;
    }
    if (body && typeof body === "object") {
      return body as T;
    }
  }
  return raw as T;
}

export class LambdaApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "LambdaApiError";
    this.status = status;
  }
}

async function postLambda<T>(payload: Record<string, unknown>): Promise<T> {
  const res = await fetch(LAMBDA_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  let raw: unknown;
  try {
    raw = await res.json();
  } catch {
    throw new LambdaApiError(`Invalid JSON response (HTTP ${res.status})`, res.status);
  }

  const data = parseLambdaJson<T & { error?: string }>(raw);

  if (!res.ok || (data && typeof data === "object" && "error" in data && data.error)) {
    const message =
      data && typeof data === "object" && "error" in data && typeof data.error === "string"
        ? data.error
        : `Request failed (HTTP ${res.status})`;
    throw new LambdaApiError(message, res.status);
  }

  return data;
}

export function fetchHealth(): Promise<HealthResponse> {
  return postLambda<HealthResponse>({ action: "health" });
}

export function processDiaryNote(
  note: string,
  userId: string,
): Promise<ProcessResponse> {
  return postLambda<ProcessResponse>({ note, user_id: userId });
}

export function createUserId(): string {
  return `usr_${crypto.randomUUID()}`;
}

export function getOrCreateUserId(): string {
  if (typeof window === "undefined") return "";
  const existing = localStorage.getItem(USER_ID_STORAGE_KEY);
  if (existing) return existing;
  const next = createUserId();
  localStorage.setItem(USER_ID_STORAGE_KEY, next);
  return next;
}
