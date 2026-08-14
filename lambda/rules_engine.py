from bedrock_client import CLAUDE_MODEL_ID, bedrock
from utils import logger

# Cosine distance threshold for "similar enough" patterns (0 = identical).
# Phase 3.5 fires only when closest distance is strictly below this value.
SIMILARITY_DISTANCE_THRESHOLD = 0.15
HIGH_SPEND_THRESHOLD = 50.0

# Emotions that trigger gentler, wellbeing-oriented alternatives (not clinical advice).
HARD_DAY_EMOTIONS = {
    'sad', 'down', 'anxious', 'stressed', 'lonely', 'overwhelmed', 'tired', 'angry',
}


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
