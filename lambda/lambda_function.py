import json
import os

import boto3
import psycopg2

# Client created once per Lambda container (warm start reuse).
bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-east-1')

CLAUDE_MODEL_ID = 'us.anthropic.claude-sonnet-4-5-20250929-v1:0'
EMBED_MODEL_ID = 'amazon.titan-embed-text-v1'


def get_database_url():
    """
    Read CockroachDB connection string from Lambda environment variables.
    Why: never hardcode passwords in source code / GitHub.
    """
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise ValueError('DATABASE_URL environment variable is not set')
    return url


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

            vector_literal = '[' + ','.join(str(x) for x in vector_embedding) + ']'
            cur.execute(
                """
                INSERT INTO life_vector_memory (entry_id, emotional_vector)
                VALUES (%s, %s::vector)
                """,
                (entry_id, vector_literal),
            )

        conn.commit()
        return str(entry_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def process_diary_note(user_note):
    """Full pipeline: Claude extract -> Titan embed -> CockroachDB save."""
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

    return {
        'entry_id': entry_id,
        'structured_data': structured_data,
        'vector_length': len(vector_embedding),
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
       -> Bedrock + INSERT into CockroachDB
    """
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
            return _response(200, {
                'message': 'Database connection successful',
                'database_check': db_check,
            })

        # --- Mode 2: full diary processing ---
        user_note = body.get('note', '')
        if not user_note:
            return _response(400, {
                'error': 'Missing required field: "note". Or send {"action":"health"} to test DB.',
            })

        # Fail fast if DB is down before spending Bedrock tokens.
        db_check = check_database()
        result = process_diary_note(user_note)

        return _response(200, {
            'message': 'AI processing and DB save successful',
            'database_check': db_check,
            **result,
        })

    except Exception as e:
        return _response(500, {'error': str(e)})
