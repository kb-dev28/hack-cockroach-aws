import json

import boto3

from db import find_similar_entries, save_to_cockroach

# Client created once per Lambda container (warm start reuse).
bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-east-1')

CLAUDE_MODEL_ID = 'us.anthropic.claude-sonnet-4-5-20250929-v1:0'
EMBED_MODEL_ID = 'amazon.titan-embed-text-v1'


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


def process_diary_note(user_note, user_id):
    """Full pipeline: Claude extract -> Titan embed -> save -> vector recall."""
    from rules_engine import build_pattern_insight

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
