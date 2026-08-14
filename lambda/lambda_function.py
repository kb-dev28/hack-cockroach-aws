import json

from bedrock_client import process_diary_note
from db import check_database
from utils import _response, log_agent_event, resolve_user_id


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
