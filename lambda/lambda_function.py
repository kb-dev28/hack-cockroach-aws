import json
import os
import re

import boto3
import psycopg2

bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-east-1')

CLAUDE_MODEL_ID = 'us.anthropic.claude-sonnet-4-5-20250929-v1:0'
EMBED_MODEL_ID = 'amazon.titan-embed-text-v1'


def extract_json(text):
    if not text or not text.strip():
        raise ValueError(f"Claude returned empty text. Raw: {repr(text)}")

    cleaned = text.strip()
    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, re.DOTALL)
    if code_block:
        cleaned = code_block.group(1).strip()

    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        return json.loads(match.group(0))

    return json.loads(cleaned)


def get_database_url():
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise ValueError('DATABASE_URL environment variable is not set')
    return url


def get_db_connection():
    return psycopg2.connect(get_database_url())


def save_to_cockroach(user_note, structured_data, vector_embedding):
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
    finally:
        conn.close()


def lambda_handler(event, context):
    try:
        body = json.loads(event.get('body', '{}'))
        user_note = body.get('note', '')

        if not user_note:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing required field: "note"'})
            }

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
            raise ValueError(f"No text block in Claude response: {claude_response}")

        structured_data = extract_json('{' + text_block['text'])

        titan_response = bedrock.invoke_model(
            modelId=EMBED_MODEL_ID,
            body=json.dumps({'inputText': user_note}),
        )

        titan_result = json.loads(titan_response['body'].read().decode('utf-8'))
        vector_embedding = titan_result['embedding']

        entry_id = save_to_cockroach(user_note, structured_data, vector_embedding)

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
            },
            'body': json.dumps({
                'message': 'AI processing and DB save successful',
                'entry_id': entry_id,
                'structured_data': structured_data,
                'vector_length': len(vector_embedding),
            }),
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)}),
        }
