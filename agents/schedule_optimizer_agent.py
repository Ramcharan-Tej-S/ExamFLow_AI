# agents/schedule_optimizer_agent.py — Timetable Optimization
"""
Pattern: Constraint-aware AI planning
Generates optimized study schedules respecting exam dates, availability, and topic difficulty.
Includes post-processing validation to enforce availability constraints.
"""
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_llm


# ─── Constants ──────────────────────────────────────────────────────
SESSION_DURATION = 60   # minutes per study block
BREAK_DURATION = 15     # minutes between blocks

# Ceiling for a single completion. Keep at or below the configured model's
# output limit (gpt-4o-mini allows 16384).
MAX_OUTPUT_TOKENS = int(os.environ.get("EXAMFLOW_MAX_OUTPUT_TOKENS", "16000"))


def _calc_plan_days(exams: list, today: datetime = None) -> int:
    """Calculate how many days to plan based on the latest exam date.
    Returns days from today to 1 day before the last exam (min 7, max 60, default 14)."""
    if today is None:
        today = datetime.now()
    if not exams:
        return 14
    latest = today.date()
    for e in exams:
        try:
            exam_dt = datetime.strptime(e.get("exam_date", ""), "%Y-%m-%d").date()
            if exam_dt > latest:
                latest = exam_dt
        except (ValueError, TypeError):
            continue
    if latest == today.date():
        return 14  # no valid exam dates found
    days = (latest - today.date()).days  # go up to 1 day before exam
    return max(7, min(days, 60))


# ─── Availability Helpers ───────────────────────────────────────────
def _build_availability_lookup(availability: list) -> dict:
    """Build a lookup: {day_name: [(start_minutes, end_minutes, is_peak, energy), ...]}"""
    lookup = {}
    for a in availability:
        day = a["day_of_week"]
        try:
            start = datetime.strptime(a["start_time"], "%H:%M")
            end = datetime.strptime(a["end_time"], "%H:%M")
            start_min = start.hour * 60 + start.minute
            end_min = end.hour * 60 + end.minute
            if end_min > start_min:
                lookup.setdefault(day, []).append(
                    (start_min, end_min, a.get("is_peak", 0), a.get("energy_level", "medium"))
                )
        except (ValueError, KeyError):
            continue
    return lookup


def _time_in_window(start_time_str: str, duration_min: int, windows: list) -> bool:
    """Check if a session (start_time + duration) fits within any availability window."""
    try:
        t = datetime.strptime(start_time_str, "%H:%M")
        session_start = t.hour * 60 + t.minute
        session_end = session_start + duration_min
    except (ValueError, TypeError):
        return False
    for win_start, win_end, _, _ in windows:
        if session_start >= win_start and session_end <= win_end:
            return True
    return False


def _generate_time_slots(availability: list) -> dict:
    """
    For each day of the week, produce a list of concrete time slots
    based on availability windows.
    E.g. available 18:30-20:30 → slots at ["18:30", "19:45"] for 60-min blocks + 15-min breaks.
    """
    lookup = _build_availability_lookup(availability)
    day_slots = {}
    for day, windows in lookup.items():
        slots = []
        for win_start, win_end, is_peak, energy in windows:
            current = win_start
            while current + SESSION_DURATION <= win_end:
                slots.append({
                    "start_time": f"{current // 60:02d}:{current % 60:02d}",
                    "duration_min": SESSION_DURATION,
                    "is_peak": is_peak,
                    "energy": energy,
                })
                current += SESSION_DURATION + BREAK_DURATION
        day_slots[day] = slots
    return day_slots


def _validate_sessions(sessions: list, availability: list) -> list:
    """
    Post-process LLM output: remove any session that falls outside availability windows.
    Also enforce max 120-min duration.
    """
    avail_lookup = _build_availability_lookup(availability)
    valid = []
    for sess in sessions:
        date_str = sess.get("date", "")
        start_time = sess.get("start_time", "")
        duration = sess.get("duration_min", 60)

        if duration > 120:
            duration = 120
            sess["duration_min"] = 120

        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            day_name = dt.strftime("%A")
        except (ValueError, TypeError):
            continue

        windows = avail_lookup.get(day_name, [])
        if not windows:
            continue

        if _time_in_window(start_time, duration, windows):
            valid.append(sess)

    return valid


# ─── Main Entry Point ──────────────────────────────────────────────
def generate_study_plan(subjects: list, topics_by_subject: dict, difficulties: dict,
                        exams: list, availability: list, existing_scores: dict = None) -> dict:
    """
    Generate an optimized study timetable.
    Uses LLM for intelligent scheduling, validates output against availability,
    and supplements with fallback if too few valid sessions.
    """
    # Build context for LLM
    subject_info = []
    for s in subjects:
        name = s["name"]
        exam = next((e for e in exams if e.get("subject_name") == name), None)
        exam_date = exam["exam_date"] if exam else "No exam scheduled"
        topic_list = topics_by_subject.get(name, [])
        topic_details = []
        for t in topic_list:
            diff = difficulties.get(t.get("topic_name", ""), {})
            topic_details.append(
                f"    - {t['topic_name']} (Difficulty: {diff.get('level', 'medium')}, "
                f"Score: {diff.get('score', 5)}/10, Est. hours: {t.get('estimated_hours', 2)}h)"
            )
        score_info = ""
        if existing_scores and name in existing_scores:
            sc = existing_scores[name]
            score_info = f", CIE Score: {sc['score']}/{sc['max_score']}"

        subject_info.append(
            f"  {name} (Exam: {exam_date}{score_info}):\n" + "\n".join(topic_details)
        )

    # Calculate how many days to plan based on the latest exam date
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    num_days = _calc_plan_days(exams, today)
    day_slots = _generate_time_slots(availability)

    allowed_slots_info = []
    for day_offset in range(num_days):
        d = today + timedelta(days=day_offset)
        day_name = d.strftime("%A")
        date_str = d.strftime("%Y-%m-%d")
        slots = day_slots.get(day_name, [])
        if slots:
            slot_strs = [f"{sl['start_time']} ({sl['duration_min']}min)" for sl in slots]
            allowed_slots_info.append(f"  {date_str} ({day_name}): {', '.join(slot_strs)}")
        else:
            allowed_slots_info.append(f"  {date_str} ({day_name}): NOT AVAILABLE")

    # The model has to emit one JSON object per slot, so the output budget has
    # to scale with the slot count — a fixed cap silently truncates the JSON on
    # any realistic schedule and drops us into the algorithmic fallback.
    expected_slots = sum(
        len(day_slots.get((today + timedelta(days=i)).strftime("%A"), []))
        for i in range(num_days)
    )
    max_tokens = max(4000, min(MAX_OUTPUT_TOKENS, 800 + 60 * expected_slots))

    llm = get_llm(temperature=0.3, max_tokens=max_tokens, json_mode=True)

    prompt = f"""You are an expert academic study planner. Create an optimized study timetable.

TODAY'S DATE: {today_str}

SUBJECTS & TOPICS:
{chr(10).join(subject_info)}

ALLOWED TIME SLOTS (you MUST ONLY use these exact dates and start times):
{chr(10).join(allowed_slots_info)}

CRITICAL RULES — FOLLOW EXACTLY:
1. ONLY schedule sessions at the ALLOWED TIME SLOTS listed above. Do NOT invent times.
2. If a day says "NOT AVAILABLE", do NOT schedule anything on that day.
3. Each session is exactly {SESSION_DURATION} minutes.
4. Harder topics should be placed in earlier/peak hours.
5. Space out revision across days (spaced repetition).
6. Leave 2-3 days before each exam for revision only.
7. Balance subjects — don't study only one subject per day.
8. If CIE scores are low for a subject, prioritize it more.
9. FILL ALL available slots — every allowed time slot should have a session.

Return JSON:
{{
    "plan_summary": "Brief overview of the study plan strategy",
    "reasoning": "Step-by-step thought process for how you created this plan",
    "sessions": [
        {{
            "subject": "Subject Name",
            "topic": "Topic Name",
            "date": "YYYY-MM-DD",
            "start_time": "HH:MM",
            "duration_min": {SESSION_DURATION},
            "priority": "high|medium|low",
            "rationale": "Why this session is planned here"
        }}
    ]
}}"""

    try:
        response = llm.invoke(prompt)
        result = json.loads(response.content)
        llm_sessions = result.get("sessions", [])

        # POST-PROCESSING: validate all sessions against availability
        valid_sessions = _validate_sessions(llm_sessions, availability)

        # If LLM produced too few valid sessions, supplement with fallback
        fallback_sessions = _fallback_schedule(subjects, topics_by_subject, exams, availability)
        min_expected = max(len(fallback_sessions) // 2, 5)

        if len(valid_sessions) < min_expected and fallback_sessions:
            used_slots = set()
            for vs in valid_sessions:
                used_slots.add((vs.get("date", ""), vs.get("start_time", "")))

            for fs in fallback_sessions:
                key = (fs.get("date", ""), fs.get("start_time", ""))
                if key not in used_slots:
                    valid_sessions.append(fs)
                    used_slots.add(key)

        # Sort by date then time
        valid_sessions.sort(key=lambda x: (x.get("date", ""), x.get("start_time", "")))

        return {
            "plan_summary": result.get("plan_summary", "AI-optimized study plan"),
            "reasoning": result.get("reasoning", ""),
            "sessions": valid_sessions,
        }

    except Exception as e:
        return {
            "plan_summary": f"Using algorithmic scheduling (LLM unavailable: {str(e)[:80]})",
            "reasoning": "LLM generation failed. Using algorithmic fallback that strictly follows your availability.",
            "sessions": _fallback_schedule(subjects, topics_by_subject, exams, availability),
        }


# ─── Fallback Scheduler ────────────────────────────────────────────
def _fallback_schedule(subjects, topics_by_subject, exams, availability):
    """
    Generate a reliable round-robin fallback schedule.
    Creates multiple 60-min study blocks with 15-min breaks,
    strictly within availability windows.
    """
    sessions = []
    today = datetime.now()

    all_topics = []
    for s in subjects:
        for t in topics_by_subject.get(s["name"], []):
            all_topics.append({"subject": s["name"], "topic": t["topic_name"]})

    if not all_topics or not availability:
        return sessions

    day_slots = _generate_time_slots(availability)
    topic_idx = 0
    num_days = _calc_plan_days(exams, today)

    for day_offset in range(num_days):
        current_date = today + timedelta(days=day_offset)
        day_name = current_date.strftime("%A")
        date_str = current_date.strftime("%Y-%m-%d")

        slots = day_slots.get(day_name, [])
        for slot in slots:
            if topic_idx >= len(all_topics):
                topic_idx = 0
            t = all_topics[topic_idx]

            sessions.append({
                "subject": t["subject"],
                "topic": t["topic"],
                "date": date_str,
                "start_time": slot["start_time"],
                "duration_min": slot["duration_min"],
                "priority": "high" if slot.get("is_peak") else "medium",
                "rationale": "Algorithmic scheduling based on your availability",
            })
            topic_idx += 1

    return sessions


# ─── Save & Recalculate ────────────────────────────────────────────
def save_study_plan(plan: dict, subject_map: dict, topic_map: dict):
    """Save generated study plan sessions to database."""
    from db.database import add_study_session, clear_sessions

    clear_sessions()
    saved = 0
    for session in plan.get("sessions", []):
        sid = subject_map.get(session.get("subject"))
        tid = topic_map.get(session.get("topic"))
        if sid:
            add_study_session(
                subject_id=sid,
                topic_id=tid,
                session_date=session.get("date", ""),
                start_time=session.get("start_time", "09:00"),
                duration_min=session.get("duration_min", 60),
                priority=session.get("priority", "medium"),
                status="planned",
            )
            saved += 1
    return saved


def recalculate_after_skip(skipped_sessions: list, remaining_sessions: list, availability: list) -> list:
    """Redistribute skipped session topics into remaining schedule."""
    llm = get_llm(temperature=0.2, max_tokens=2000, json_mode=True)

    prompt = f"""Some study sessions were skipped and need to be redistributed.

SKIPPED SESSIONS:
{json.dumps(skipped_sessions, indent=2)}

REMAINING SESSIONS:
{json.dumps(remaining_sessions[:20], indent=2)}

AVAILABLE SLOTS:
{json.dumps(availability[:10], indent=2)}

Redistribute the skipped topics into available slots. Maintain priority and ensure coverage.

Return JSON:
{{
    "adjusted_sessions": [
        {{
            "subject": "Subject Name",
            "topic": "Topic Name",
            "date": "YYYY-MM-DD",
            "start_time": "HH:MM",
            "duration_min": 60,
            "priority": "high|medium|low",
            "rationale": "Redistributed from skipped session"
        }}
    ]
}}"""

    try:
        response = llm.invoke(prompt)
        result = json.loads(response.content)
        validated = _validate_sessions(result.get("adjusted_sessions", []), availability)
        return validated
    except Exception:
        return []
