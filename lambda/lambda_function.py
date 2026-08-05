import json
import logging
import os

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

# Cached across warm invocations; refreshed only on cold start.
_CACHED_DATABASE_URL = None


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
SIMILARITY_DISTANCE_THRESHOLD = 0.15


def _vector_literal(vector_embedding):
    """Convert a Python list of floats into CockroachDB VECTOR literal text."""
    return '[' + ','.join(str(x) for x in vector_embedding) + ']'


def save_to_cockroach(user_note, structured_data, vector_embedding):
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
                    user_note, detected_emotion, main_meal, total_spend,
                    main_event, people_involved, weather_condition
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
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
                INSERT INTO life_vector_memory (entry_id, emotional_vector)
                VALUES (%s, %s::vector)
                """,
                (entry_id, _vector_literal(vector_embedding)),
            )

        conn.commit()
        return str(entry_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def find_similar_entries(vector_embedding, current_entry_id, limit=3):
    """
    Agentic memory recall: find past days with closest emotional meaning.
    Uses CockroachDB cosine distance operator <=> on the VECTOR index.
    Lower distance = more similar.
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
                WHERE lvm.entry_id != %s::uuid
                ORDER BY distance ASC
                LIMIT %s
                """,
                (
                    _vector_literal(vector_embedding),
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
    Turn nearest-neighbor vector hits into an autonomous agent alert.
    Crosses emotion/meal/spend/people from the closest past day.
    """
    if not similar_entries:
        return {
            'has_pattern': False,
            'summary': 'No past diary entries yet. Keep journaling so the agent can detect patterns.',
            'similar_entries': [],
            'closest_distance': None,
        }

    closest = similar_entries[0]
    distance = closest.get('distance')
    has_pattern = (
        distance is not None and distance <= SIMILARITY_DISTANCE_THRESHOLD
    )

    if has_pattern:
        summary = (
            f"Pattern detected: today feels similar to a past day "
            f"(emotion={closest.get('detected_emotion')}, "
            f"event={closest.get('main_event')}, "
            f"people={closest.get('people_involved')}, "
            f"meal={closest.get('main_meal')}, "
            f"spend=${closest.get('total_spend')}, "
            f"weather={closest.get('weather_condition')}). "
            f"Cosine distance={distance:.4f}."
        )
    else:
        summary = (
            f"Closest past day found, but not similar enough yet "
            f"(distance={distance}). Keep journaling to strengthen memory."
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
    }


def process_diary_note(user_note):
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

    entry_id = save_to_cockroach(user_note, structured_data, vector_embedding)
    similar_entries = find_similar_entries(vector_embedding, entry_id, limit=3)
    pattern_insight = build_pattern_insight(structured_data, similar_entries)

    return {
        'entry_id': entry_id,
        'structured_data': structured_data,
        'vector_length': len(vector_embedding),
        'pattern_insight': pattern_insight,
    }


def _response(status_code, payload):
    """Standard API Gateway / Function URL response shape."""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(payload),
    }


def lambda_handler(event, context):
    """
    AWS Lambda entrypoint.

    Modes:
    1) Health / DB test (recommended first):
       POST {"action": "health"}
       -> SELECT 1 + COUNT(*) on both tables

    2) Full diary pipeline:
       POST {"note": "Today I felt sad..."}
       -> Bedrock + INSERT into CockroachDB + vector recall
    """
    request_id = getattr(context, 'aws_request_id', None)

    try:
        # Support both:
        # 1) Direct invoke / console test: {"action":"health"} or {"note":"..."}
        # 2) API Gateway / Function URL: {"body":"{\"action\":\"health\"}"}
        if isinstance(event, dict) and ('action' in event or 'note' in event):
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

        log_agent_event(
            'DIARY_PROCESS_START',
            request_id=request_id,
            note_length=len(user_note),
        )

        # Fail fast if DB is down before spending Bedrock tokens.
        db_check = check_database()
        result = process_diary_note(user_note)

        insight = result.get('pattern_insight') or {}
        log_agent_event(
            'PATTERN_RECALL_SUCCESS',
            request_id=request_id,
            entry_id=result.get('entry_id'),
            closest_distance=insight.get('closest_distance'),
            action_triggered=bool(insight.get('has_pattern')),
            similar_count=len(insight.get('similar_entries') or []),
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
