import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DATABASE_SECRET_NAME = 'hack-cockroach-aws/database-url'
DEFAULT_USER_ID = 'default_user'


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


def _response(status_code, payload, extra_headers=None):
    """Standard API Gateway / Function URL response shape.
    CORS headers are handled by the Function URL config (AWS injects them
    automatically) — adding them here too causes duplicate headers.
    """
    headers = {
        'Content-Type': 'application/json',
    }
    if extra_headers:
        headers.update(extra_headers)
    return {
        'statusCode': status_code,
        'headers': headers,
        'body': json.dumps(payload) if payload is not None else '',
    }