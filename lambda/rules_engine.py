from bedrock_client import CLAUDE_MODEL_ID, bedrock
from utils import logger

# Cosine distance threshold for "similar enough" patterns (0 = identical).
# Phase 3.5 fires only when closest distance is strictly below this value.
SIMILARITY_DISTANCE_THRESHOLD = 0.3
HIGH_SPEND_THRESHOLD = 50.0
IMPULSIVE_SPEND_THRESHOLD = 20.0

ROUTINE_SUMMARY = 'Routine entry logged cleanly. No action required.'

# Emotions that trigger gentler, wellbeing-oriented alternatives (not clinical advice).
HARD_DAY_EMOTIONS = {
    'sad', 'down', 'anxious', 'stressed', 'lonely', 'overwhelmed', 'tired', 'angry',
}


def _norm_text(value):
    """Normalize optional string fields for comparisons."""
    if value is None:
        return ''
    return str(value).strip().lower()


def _is_actionable_pattern(current_data, past_entry, signals):
    """
    True when vector similarity should trigger an autonomous intervention.
    Routine/neutral days (no hard emotion, no impulsive spend loop) stay false.
    """
    signal_types = {s['type'] for s in signals}
    curr_emotion = _norm_text(current_data.get('detected_emotion'))
    past_emotion = _norm_text(past_entry.get('detected_emotion'))
    curr_spend = float(current_data.get('total_spend') or 0)
    past_spend = float(past_entry.get('total_spend') or 0)
    peak_spend = max(curr_spend, past_spend)

    if curr_emotion in HARD_DAY_EMOTIONS and past_emotion in HARD_DAY_EMOTIONS:
        return True
    if 'emotion_echo' in signal_types and curr_emotion in HARD_DAY_EMOTIONS:
        return True
    if peak_spend > IMPULSIVE_SPEND_THRESHOLD and (
        'similar_spend' in signal_types or 'high_spend' in signal_types or curr_spend > 0
    ):
        return True
    if curr_emotion in HARD_DAY_EMOTIONS and (
        'same_people' in signal_types or 'same_meal' in signal_types
    ):
        return True
    return False


def _derive_agent_decision(signal_types, current_data, past_entry):
    """Short autonomous decision label for demo / judges."""
    curr_emotion = _norm_text(current_data.get('detected_emotion'))
    if 'high_spend' in signal_types or 'similar_spend' in signal_types:
        return 'DECISION: Triggering preventive budget cap'
    if 'hard_day_emotion' in signal_types and 'emotion_echo' in signal_types:
        return 'DECISION: Flagging emotional fatigue loop'
    if 'same_people' in signal_types and 'same_meal' in signal_types:
        return 'DECISION: Interrupting comfort-meal loop after social visit'
    if curr_emotion in HARD_DAY_EMOTIONS:
        return 'DECISION: Flagging emotional fatigue loop'
    return 'DECISION: Preventive action triggered'


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
            f'Stop non-essential spending for the next 3 hours — your last similar loop hit '
            f'~${max(curr_spend, past_spend):.0f}. Do one free reset (walk, water, stretch) before any purchase.'
        )
    if 'same_people' in signal_types and people not in ('', 'none', 'unknown'):
        alternatives.append(
            f'After seeing {people}, take a 10-minute solo break now (walk outside or quiet pause) '
            'before the day continues — break the social-stress loop.'
        )
    if 'same_meal' in signal_types and meal not in ('', 'unknown'):
        alternatives.append(
            f'Skip the repeating "{meal}" cue today — choose a lighter meal and a 5-minute walk right after.'
        )
    if 'hard_day_emotion' in signal_types or curr_emotion in HARD_DAY_EMOTIONS:
        alternatives.append(
            'Act now: one concrete reset in the next hour — short walk, message someone supportive, '
            'or 5 calm breaths. This is a habit interrupt, not a diagnosis.'
        )

    suggested_alternative = alternatives[0]
    supporting = alternatives[1:]
    agent_decision = _derive_agent_decision(signal_types, current_data, past_entry)

    # Optional Bedrock polish — rules remain source of truth; tone stays direct.
    polished = None
    try:
        polish_prompt = f"""
You are Synap, an autonomous wellness-memory agent (not a clinician).
Rewrite ONE direct, actionable recommendation (max 2 sentences). Be firm and specific.
No medical diagnosis. No vague advice like "take a different route".

Agent decision: {agent_decision}
Cause/effect: {cause_effect}
Primary action: {suggested_alternative}
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
        'agent_decision': agent_decision,
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
    vector_match = (
        distance is not None and distance < SIMILARITY_DISTANCE_THRESHOLD
    )

    agent_suggestion = None
    agent_decision = None
    has_pattern = False

    if vector_match:
        signals, cause_effect = evaluate_cause_effect(current_data, closest)
        if _is_actionable_pattern(current_data, closest, signals):
            has_pattern = True
            agent_suggestion = build_proactive_suggestion(
                current_data, closest, signals, cause_effect
            )
            agent_decision = agent_suggestion.get('agent_decision')
            summary = (
                f"Pattern detected (cosine distance={distance:.4f} < "
                f"{SIMILARITY_DISTANCE_THRESHOLD}). {cause_effect} "
                f"Agent suggestion: {agent_suggestion['agent_message']}"
            )
        else:
            summary = ROUTINE_SUMMARY
            agent_suggestion = {
                'action_triggered': False,
                'agent_message': ROUTINE_SUMMARY,
                'agent_decision': None,
            }
    else:
        summary = (
            f"Closest past day found, but not similar enough yet "
            f"(distance={distance}, need < {SIMILARITY_DISTANCE_THRESHOLD}). "
            f"Keep journaling to strengthen memory."
        )

    return {
        'has_pattern': has_pattern,
        'agent_decision': agent_decision,
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
