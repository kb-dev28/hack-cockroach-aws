import json
import logging

import boto3
import psycopg2

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Clients created once per Lambda container (warm start reuse).
bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-east-1')
secretsmanager = boto3.client(service_name='secretsmanager', region_name='us-east-1')

CLAUDE_MODEL_ID = 'us.anthropic.claude-sonnet-4-5-20250929-v1:0'
EMBED_MODEL_ID = 'amazon.titan-embed-text-v1'
DATABASE_SECRET_NAME = 'hack-cockroach-aws/database-url'
DEFAULT_USER_ID = 'default_user'

# Cached across warm invocations; refreshed only on cold start.
_CACHED_DATABASE_URL = None


def resolve_user_id(body):
    """Per-user memory isolation; anonymous clients send user_id from localStorage."""
    raw = body.get('user_id')
    if raw is None or str(raw).strip() == '':
        return DEFAULT_USER_ID
    return str(raw).strip()[:128]


def log_agent_event(event_name, request_id=None, **fields):
    """Emit one CloudWatch-friendly JSON log line for agent observability."""
    payload = {'event': event_name, **fields}
    if request_id:
        payload['request_id'] = request_id
    logger.info(json.dumps(payload, default=str))


def get_database_url():
    """
    Load CockroachDB connection string from AWS Secrets Manager.
    Cached at module level so Secrets Manager is called on cold start only.
    PGSSLROOTCERT still comes from a normal Lambda environment variable.
    """
    global _CACHED_DATABASE_URL

    if _CACHED_DATABASE_URL:
        return _CACHED_DATABASE_URL

    try:
        response = secretsmanager.get_secret_value(SecretId=DATABASE_SECRET_NAME)
    except Exception as e:
        raise RuntimeError(
            f'Failed to read secret "{DATABASE_SECRET_NAME}" from Secrets Manager: {e}'
        ) from e

    secret_string = response.get('SecretString')
    if not secret_string:
        raise RuntimeError(
            f'Secret "{DATABASE_SECRET_NAME}" has no SecretString payload'
        )

    try:
        secret_data = json.loads(secret_string)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f'Secret "{DATABASE_SECRET_NAME}" is not valid JSON: {e}'
        ) from e

    url = secret_data.get('DATABASE_URL')
    if not url:
        raise RuntimeError(
            f'Secret "{DATABASE_SECRET_NAME}" is missing JSON key "DATABASE_URL"'
        )

    _CACHED_DATABASE_URL = url
    return _CACHED_DATABASE_URL


def get_db_connection():
    """
    Open a PostgreSQL-compatible connection to CockroachDB via psycopg2.
    Why: CockroachDB speaks the Postgres wire protocol, so psycopg2 works.
    """
    return psycopg2.connect(get_database_url())


def check_database():
    """
    Connectivity smoke test used before heavier AI + INSERT work.
    Why: if SELECT 1 fails, Bedrock/INSERT will also fail — fail fast and clear.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT 1 AS ok')
            ok = cur.fetchone()[0]

            cur.execute('SELECT COUNT(*) FROM diary_entries')
            diary_count = cur.fetchone()[0]

            cur.execute('SELECT COUNT(*) FROM life_vector_memory')
            vector_count = cur.fetchone()[0]

        return {
            'ok': ok,
            'diary_entries_count': diary_count,
            'life_vector_memory_count': vector_count,
        }
    finally:
        conn.close()


def extract_json(text):
    """Parse Claude output even if it wraps JSON in markdown fences."""
    if not text or not text.strip():
        raise ValueError(f'Claude returned empty text. Raw: {repr(text)}')

    cleaned = text.strip()
    if '```' in cleaned:
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start != -1 and end != -1:
            cleaned = cleaned[start:end + 1]
    else:
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start != -1 and end != -1:
            cleaned = cleaned[start:end + 1]

    return json.loads(cleaned)


# Cosine distance threshold for "similar enough" patterns (0 = identical).
# Phase 3.5 fires only when closest distance is strictly below this value.
SIMILARITY_DISTANCE_THRESHOLD = 0.15
HIGH_SPEND_THRESHOLD = 50.0

# Emotions that trigger gentler, wellbeing-oriented alternatives (not clinical advice).
HARD_DAY_EMOTIONS = {
    'sad', 'down', 'anxious', 'stressed', 'lonely', 'overwhelmed', 'tired', 'angry',
}


def _vector_literal(vector_embedding):
    """Convert a Python list of floats into CockroachDB VECTOR literal text."""
    return '[' + ','.join(str(x) for x in vector_embedding) + ']'


def _norm_text(value):
    """Normalize optional string fields for comparisons."""
    if value is None:
        return ''
    return str(value).strip().lower()


def evaluate_cause_effect(current_data, past_entry):
    """
    Phase 3.5 evaluative rules: cross today's signals with the closest past day.
    Returns structured signals + a short cause/effect narrative (not a diagnosis).
    """
    signals = []
    past_emotion = _norm_text(past_entry.get('detected_emotion'))
    curr_emotion = _norm_text(current_data.get('detected_emotion'))
    past_spend = float(past_entry.get('total_spend') or 0)
    curr_spend = float(current_data.get('total_spend') or 0)
    past_people = _norm_text(past_entry.get('people_involved'))
    curr_people = _norm_text(current_data.get('people_involved'))
    past_meal = _norm_text(past_entry.get('main_meal'))
    curr_meal = _norm_text(current_data.get('main_meal'))
    past_event = _norm_text(past_entry.get('main_event'))
    curr_event = _norm_text(current_data.get('main_event'))
    past_weather = _norm_text(past_entry.get('weather_condition'))
    curr_weather = _norm_text(current_data.get('weather_condition'))

    if curr_emotion and past_emotion and curr_emotion == past_emotion:
        signals.append({
            'type': 'emotion_echo',
            'detail': f'Emotion "{curr_emotion}" also appeared on the closest past day.',
        })

    if curr_emotion in HARD_DAY_EMOTIONS or past_emotion in HARD_DAY_EMOTIONS:
        signals.append({
            'type': 'hard_day_emotion',
            'detail': f'Hard-day emotion signal (today={curr_emotion or "unknown"}, past={past_emotion or "unknown"}).',
        })

    if past_spend >= HIGH_SPEND_THRESHOLD or curr_spend >= HIGH_SPEND_THRESHOLD:
        signals.append({
            'type': 'high_spend',
            'detail': f'Spend signal crossed ${HIGH_SPEND_THRESHOLD:.0f} (today=${curr_spend:.2f}, past=${past_spend:.2f}).',
        })
    elif past_spend > 0 and curr_spend > 0 and abs(curr_spend - past_spend) <= 15:
        signals.append({
            'type': 'similar_spend',
            'detail': f'Similar spend pattern (today=${curr_spend:.2f}, past=${past_spend:.2f}).',
        })

    if (
        past_people
        and curr_people
        and past_people not in ('none', 'unknown')
        and curr_people not in ('none', 'unknown')
        and (past_people in curr_people or curr_people in past_people)
    ):
        signals.append({
            'type': 'same_people',
            'detail': f'Same social context (today={curr_people}, past={past_people}).',
        })

    if (
        past_meal
        and curr_meal
        and past_meal not in ('unknown',)
        and curr_meal not in ('unknown',)
        and past_meal == curr_meal
    ):
        signals.append({
            'type': 'same_meal',
            'detail': f'Same meal cue repeated ({curr_meal}).',
        })

    if (
        past_event
        and curr_event
        and past_event not in ('unknown',)
        and curr_event not in ('unknown',)
        and (past_event in curr_event or curr_event in past_event)
    ):
        signals.append({
            'type': 'same_event',
            'detail': f'Similar event context (today={curr_event}, past={past_event}).',
        })

    if (
        past_weather
        and curr_weather
        and past_weather not in ('unknown',)
        and curr_weather not in ('unknown',)
        and past_weather == curr_weather
    ):
        signals.append({
            'type': 'same_weather',
            'detail': f'Same weather context ({curr_weather}).',
        })

    cause_bits = []
    if any(s['type'] == 'same_people' for s in signals):
        cause_bits.append(f'interaction involving {curr_people or past_people}')
    if any(s['type'] == 'same_event' for s in signals):
        cause_bits.append(f'activity around "{curr_event or past_event}"')
    if any(s['type'] in ('high_spend', 'similar_spend') for s in signals):
        cause_bits.append(f'spending near ${max(curr_spend, past_spend):.0f}')
    if any(s['type'] == 'same_meal' for s in signals):
        cause_bits.append(f'meal cue "{curr_meal}"')
    if any(s['type'] == 'same_weather' for s in signals):
        cause_bits.append(f'{curr_weather} weather')

    if not cause_bits:
        cause_bits.append('overlapping life context from vector memory')

    effect = curr_emotion or past_emotion or 'a similar emotional state'
    cause_effect = (
        f"When {' + '.join(cause_bits)} showed up before, the linked effect was "
        f'feeling {effect}. Today\'s note echoes that same loop.'
    )

    return signals, cause_effect


def build_proactive_suggestion(current_data, past_entry, signals, cause_effect):
    """
    Autonomous Phase 3.5 action: suggest a practical alternative (never clinical).
    Uses evaluative rules first; optionally softens wording via Bedrock with fallback.
    """
    curr_emotion = _norm_text(current_data.get('detected_emotion'))
    past_spend = float(past_entry.get('total_spend') or 0)
    curr_spend = float(current_data.get('total_spend') or 0)
    people = _norm_text(current_data.get('people_involved')) or _norm_text(
        past_entry.get('people_involved')
    )
    meal = _norm_text(current_data.get('main_meal')) or _norm_text(
        past_entry.get('main_meal')
    )
    signal_types = {s['type'] for s in signals}

    alternatives = []
    if 'high_spend' in signal_types or 'similar_spend' in signal_types:
        alternatives.append(
            f'Cap discretionary spend for the next few hours (past spike ~${max(curr_spend, past_spend):.0f}) '
            'and pick one free reset instead of another purchase.'
        )
    if 'same_people' in signal_types and people not in ('', 'none', 'unknown'):
        alternatives.append(
            f'After time with {people}, schedule a 10-minute solo decompress '
            '(walk, water, inbox pause) before the day continues.'
        )
    if 'same_meal' in signal_types and meal not in ('', 'unknown'):
        alternatives.append(
            f'Swap the repeating "{meal}" cue once today for a lighter meal or a short walk after eating.'
        )
    if 'hard_day_emotion' in signal_types or curr_emotion in HARD_DAY_EMOTIONS:
        alternatives.append(
            'Choose one small restorative action you control in the next hour '
            '(short walk outside, message a supportive friend, or 5 calm breaths)—not a diagnosis, just a reset.'
        )
    if not alternatives:
        alternatives.append(
            'Break the echoed pattern with one tiny change today: different route, shorter errand, or a planned pause.'
        )

    suggested_alternative = alternatives[0]
    supporting = alternatives[1:]

    # Optional Bedrock polish for demo-quality prose; rules remain source of truth.
    polished = None
    try:
        polish_prompt = f"""
You are Anima, a proactive wellness-memory agent (not a clinician).
Given this cause/effect and rule-based alternative, rewrite ONE short suggestion (max 2 sentences).
Rules: practical, optional, no medical/clinical diagnosis, no commands that sound mandatory.

Cause/effect: {cause_effect}
Primary alternative: {suggested_alternative}
"""
        polish_response = bedrock.converse(
            modelId=CLAUDE_MODEL_ID,
            messages=[{'role': 'user', 'content': [{'text': polish_prompt}]}],
            inferenceConfig={'maxTokens': 120, 'temperature': 0.2},
        )
        blocks = polish_response['output']['message'].get('content', [])
        text_block = next((b for b in blocks if 'text' in b), None)
        if text_block and text_block['text'].strip():
            polished = text_block['text'].strip()
    except Exception as e:
        logger.warning('Proactive suggestion polish failed; using rule text: %s', e)

    return {
        'action_triggered': True,
        'cause_effect': cause_effect,
        'signals': signals,
        'suggested_alternative': suggested_alternative,
        'supporting_alternatives': supporting,
        'agent_message': polished or suggested_alternative,
        'ethical_note': (
            'Suggestion only — not a diagnosis. You choose whether to try the alternative.'
        ),
    }


def save_to_cockroach(user_note, structured_data, vector_embedding, user_id):
    """
    Persist structured diary fields + embedding in one transaction.
    Why: FK requires diary_entries.id before life_vector_memory.entry_id.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO diary_entries (
                    user_id, user_note, detected_emotion, main_meal, total_spend,
                    main_event, people_involved, weather_condition
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    user_id,
                    user_note,
                    structured_data.get('detected_emotion'),
                    structured_data.get('main_meal'),
                    structured_data.get('total_spend', 0.00),
                    structured_data.get('main_event'),
                    structured_data.get('people_involved'),
                    structured_data.get('weather_condition'),
                ),
            )
            entry_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO life_vector_memory (user_id, entry_id, emotional_vector)
                VALUES (%s, %s, %s::vector)
                """,
                (user_id, entry_id, _vector_literal(vector_embedding)),
            )

        conn.commit()
        return str(entry_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def find_similar_entries(vector_embedding, current_entry_id, user_id, limit=3):
    """
    Agentic memory recall scoped to one user_id.
    Uses CockroachDB cosine distance (<=>) on emotional_vector.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    de.id,
                    de.user_note,
                    de.detected_emotion,
                    de.main_meal,
                    de.total_spend,
                    de.main_event,
                    de.people_involved,
                    de.weather_condition,
                    de.created_at,
                    (lvm.emotional_vector <=> %s::vector) AS distance
                FROM life_vector_memory lvm
                JOIN diary_entries de ON de.id = lvm.entry_id
                WHERE lvm.user_id = %s
                  AND lvm.entry_id != %s::uuid
                ORDER BY distance ASC
                LIMIT %s
                """,
                (
                    _vector_literal(vector_embedding),
                    user_id,
                    current_entry_id,
                    limit,
                ),
            )
            rows = cur.fetchall()

        similar = []
        for row in rows:
            similar.append({
                'entry_id': str(row[0]),
                'user_note': row[1],
                'detected_emotion': row[2],
                'main_meal': row[3],
                'total_spend': float(row[4]) if row[4] is not None else 0.0,
                'main_event': row[5],
                'people_involved': row[6],
                'weather_condition': row[7],
                'created_at': row[8].isoformat() if row[8] is not None else None,
                'distance': float(row[9]) if row[9] is not None else None,
            })
        return similar
    finally:
        conn.close()


def build_pattern_insight(current_data, similar_entries):
    """
    Turn nearest-neighbor vector hits into an autonomous Phase 3.5 agent alert.
    If distance < 0.15: evaluate cause/effect and propose a practical alternative.
    """
    if not similar_entries:
        return {
            'has_pattern': False,
            'summary': 'No past diary entries yet. Keep journaling so the agent can detect patterns.',
            'similar_entries': [],
            'closest_distance': None,
            'agent_suggestion': None,
        }

    closest = similar_entries[0]
    distance = closest.get('distance')
    has_pattern = (
        distance is not None and distance < SIMILARITY_DISTANCE_THRESHOLD
    )

    agent_suggestion = None
    if has_pattern:
        signals, cause_effect = evaluate_cause_effect(current_data, closest)
        agent_suggestion = build_proactive_suggestion(
            current_data, closest, signals, cause_effect
        )
        summary = (
            f"Pattern detected (cosine distance={distance:.4f} < {SIMILARITY_DISTANCE_THRESHOLD}). "
            f"{cause_effect} Agent suggestion: {agent_suggestion['agent_message']}"
        )
    else:
        summary = (
            f"Closest past day found, but not similar enough yet "
            f"(distance={distance}, need < {SIMILARITY_DISTANCE_THRESHOLD}). "
            f"Keep journaling to strengthen memory."
        )

    return {
        'has_pattern': has_pattern,
        'summary': summary,
        'current': {
            'detected_emotion': current_data.get('detected_emotion'),
            'main_event': current_data.get('main_event'),
            'people_involved': current_data.get('people_involved'),
            'main_meal': current_data.get('main_meal'),
            'total_spend': current_data.get('total_spend'),
            'weather_condition': current_data.get('weather_condition'),
        },
        'similar_entries': similar_entries,
        'closest_distance': distance,
        'agent_suggestion': agent_suggestion,
    }


def process_diary_note(user_note, user_id):
    """Full pipeline: Claude extract -> Titan embed -> save -> vector recall."""
    claude_prompt = f"""
Analyze the following personal diary entry and extract:
- detected_emotion (Strictly ONE word in English)
- main_meal (Primary food mentioned, or "unknown")
- total_spend (Number only. If none, return 0.00)
- main_event (Main activity, max 5 words. "unknown" if none)
- people_involved (Comma-separated. "none" if none)
- weather_condition (sunny, rainy, cloudy, cold, hot, unknown)

Diary entry: "{user_note}"

Return ONLY valid JSON with keys:
"detected_emotion", "main_meal", "total_spend", "main_event", "people_involved", "weather_condition".
"""

    claude_response = bedrock.converse(
        modelId=CLAUDE_MODEL_ID,
        messages=[
            {'role': 'user', 'content': [{'text': claude_prompt}]},
            {'role': 'assistant', 'content': [{'text': '{'}]},
        ],
        inferenceConfig={
            'maxTokens': 300,
            'temperature': 0.0,
        },
    )

    content_blocks = claude_response['output']['message'].get('content', [])
    text_block = next((b for b in content_blocks if 'text' in b), None)
    if not text_block:
        raise ValueError(f'No text block in Claude response: {claude_response}')

    structured_data = extract_json('{' + text_block['text'])

    titan_response = bedrock.invoke_model(
        modelId=EMBED_MODEL_ID,
        body=json.dumps({'inputText': user_note}),
    )
    titan_result = json.loads(titan_response['body'].read().decode('utf-8'))
    vector_embedding = titan_result['embedding']

    entry_id = save_to_cockroach(user_note, structured_data, vector_embedding, user_id)
    similar_entries = find_similar_entries(
        vector_embedding, entry_id, user_id, limit=3
    )
    pattern_insight = build_pattern_insight(structured_data, similar_entries)

    return {
        'user_id': user_id,
        'entry_id': entry_id,
        'structured_data': structured_data,
        'vector_length': len(vector_embedding),
        'pattern_insight': pattern_insight,
    }


def _response(status_code, payload, extra_headers=None):
    """Standard API Gateway / Function URL response shape with CORS."""
    headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
    }
    if extra_headers:
        headers.update(extra_headers)
    return {
        'statusCode': status_code,
        'headers': headers,
        'body': json.dumps(payload) if payload is not None else '',
    }


def _is_options_request(event):
    if not isinstance(event, dict):
        return False
    method = (
        event.get('requestContext', {}).get('http', {}).get('method')
        or event.get('httpMethod')
    )
    return method == 'OPTIONS'


def lambda_handler(event, context):
    """
    AWS Lambda entrypoint.

    Modes:
    1) Health / DB test (recommended first):
       POST {"action": "health"}
       -> SELECT 1 + COUNT(*) on both tables

    2) Full diary pipeline:
       POST {"note": "Today I felt sad...", "user_id": "usr_..."}
       -> Bedrock + INSERT into CockroachDB + per-user vector recall
    """
    request_id = getattr(context, 'aws_request_id', None)

    if _is_options_request(event):
        return _response(204, None)

    try:
        # Support both:
        # 1) Direct invoke / console test: {"action":"health"} or {"note":"..."}
        # 2) API Gateway / Function URL: {"body":"{\"action\":\"health\"}"}
        if isinstance(event, dict) and (
            'action' in event or 'note' in event or 'user_id' in event
        ):
            body = event
        else:
            raw_body = event.get('body', '{}') if isinstance(event, dict) else '{}'
            if isinstance(raw_body, dict):
                body = raw_body
            else:
                body = json.loads(raw_body or '{}')

        action = body.get('action', 'process')

        # --- Mode 1: prove CockroachDB connectivity without calling Bedrock ---
        if action == 'health':
            db_check = check_database()
            log_agent_event(
                'HEALTH_CHECK_SUCCESS',
                request_id=request_id,
                diary_entries_count=db_check.get('diary_entries_count'),
                life_vector_memory_count=db_check.get('life_vector_memory_count'),
            )
            return _response(200, {
                'message': 'Database connection successful',
                'database_check': db_check,
            })

        # --- Mode 2: full diary processing ---
        user_note = body.get('note', '')
        if not user_note:
            log_agent_event(
                'VALIDATION_ERROR',
                request_id=request_id,
                reason='missing_note',
            )
            return _response(400, {
                'error': 'Missing required field: "note". Or send {"action":"health"} to test DB.',
            })

        user_id = resolve_user_id(body)

        log_agent_event(
            'DIARY_PROCESS_START',
            request_id=request_id,
            note_length=len(user_note),
            user_id=user_id,
        )

        # Fail fast if DB is down before spending Bedrock tokens.
        db_check = check_database()
        result = process_diary_note(user_note, user_id)

        insight = result.get('pattern_insight') or {}
        suggestion = insight.get('agent_suggestion') or {}
        log_agent_event(
            'PATTERN_RECALL_SUCCESS',
            request_id=request_id,
            user_id=user_id,
            entry_id=result.get('entry_id'),
            closest_distance=insight.get('closest_distance'),
            action_triggered=bool(insight.get('has_pattern')),
            similar_count=len(insight.get('similar_entries') or []),
            agent_suggestion_triggered=bool(suggestion.get('action_triggered')),
            cause_effect=suggestion.get('cause_effect'),
        )

        return _response(200, {
            'message': 'AI processing, memory save, and pattern recall successful',
            'database_check': db_check,
            **result,
        })

    except Exception as e:
        log_agent_event(
            'AGENT_ERROR',
            request_id=request_id,
            error=str(e),
        )
        return _response(500, {'error': str(e)})
