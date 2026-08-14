import json

import boto3
import psycopg2

from utils import DATABASE_SECRET_NAME

# Client created once per Lambda container (warm start reuse).
secretsmanager = boto3.client(service_name='secretsmanager', region_name='us-east-1')

# Cached across warm invocations; refreshed only on cold start.
_CACHED_DATABASE_URL = None


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


def _vector_literal(vector_embedding):
    """Convert a Python list of floats into CockroachDB VECTOR literal text."""
    return '[' + ','.join(str(x) for x in vector_embedding) + ']'


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
