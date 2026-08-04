import pytest

from app.application.context_service import ContextService


def test_context_uses_the_latest_transcript_and_authorized_screen_text() -> None:
    context = ContextService(
        max_transcript_characters=300,
        max_screen_characters=50,
    )
    context.update_screen("Visible task: submit the report on Friday.")
    context.record_transcript("Can you summarize the deadline?", "microphone")

    prompt = context.build_prompt()

    assert "Most recent utterance (microphone):" in prompt
    assert "Can you summarize the deadline?" in prompt
    assert "Visible task: submit the report on Friday." in prompt


def test_context_discards_oldest_transcripts_when_its_limit_is_reached() -> None:
    context = ContextService(
        max_transcript_characters=30,
        max_screen_characters=50,
    )
    context.record_transcript("first finalized sentence", "microphone")
    context.record_transcript("latest question", "microphone")

    prompt = context.build_prompt()

    assert "latest question" in prompt
    assert "first finalized sentence" not in prompt


def test_context_requires_a_final_transcript() -> None:
    context = ContextService(
        max_transcript_characters=300,
        max_screen_characters=50,
    )

    with pytest.raises(ValueError, match="context_missing_final_transcript"):
        context.build_prompt()


def test_explicit_profile_request_includes_the_prepared_profile() -> None:
    context = ContextService(
        max_transcript_characters=300,
        max_screen_characters=50,
    )
    context.update_candidate_profile(
        {"candidate": {"name": "Dileep"}, "summary": "AI Engineer"}
    )

    prompt = context.build_user_prompt("Introduce yourself", True)

    assert '"name":"Dileep"' in prompt
    assert '"summary":"AI Engineer"' in prompt


def test_regular_chat_does_not_include_the_candidate_profile() -> None:
    context = ContextService(
        max_transcript_characters=300,
        max_screen_characters=50,
    )
    context.update_candidate_profile({"candidate": {"name": "Dileep"}})

    prompt = context.build_user_prompt("Explain the screen")

    assert '"name":"Dileep"' not in prompt


def test_profile_knowledge_base_guides_matching_project_answers() -> None:
    context = ContextService(
        max_transcript_characters=300,
        max_screen_characters=50,
    )
    context.update_candidate_profile(
        {
            "sections": {
                "projects": [
                    {
                        "title": "Advanced RAG Pipeline",
                        "details": ["Built semantic search with Weaviate."],
                    }
                ]
            }
        }
    )

    prompt = context.build_user_prompt("Explain Advanced RAG", True)

    assert "Advanced RAG Pipeline" in prompt
    assert "authoritative source" in prompt
    assert "Do not invent details" in prompt


def test_profile_coaching_request_requires_a_first_person_answer() -> None:
    context = ContextService(
        max_transcript_characters=300,
        max_screen_characters=50,
    )
    context.update_candidate_profile(
        {"candidate": {"name": "Dileep"}, "summary": "AI Engineer"}
    )

    prompt = context.build_user_prompt("How could I answer: introduce yourself?", True)

    assert "first-person candidate answer" in prompt
    assert "Do not ask the user to repeat" in prompt


def test_profile_experience_level_controls_answer_seniority() -> None:
    context = ContextService(
        max_transcript_characters=300,
        max_screen_characters=50,
    )
    context.update_candidate_profile(
        {
            "candidate": {"name": "Dileep"},
            "session_preferences": {"experience_level": "5 years"},
        }
    )

    prompt = context.build_user_prompt("Introduce yourself", True)

    assert '"experience_level":"5 years"' in prompt
    assert "adapt the answer depth, terminology, and scope" in prompt
    assert "never claim experience or facts that conflict with the resume" in prompt


def test_screen_prompt_solves_detected_questions_without_follow_up() -> None:
    context = ContextService(
        max_transcript_characters=300,
        max_screen_characters=1_000,
    )
    context.update_screen(
        "Which data structure uses FIFO? A. Stack B. Queue C. Tree D. Heap"
    )

    prompt = context.build_screen_prompt()

    assert "without waiting for another user message" in prompt
    assert "Multiple choice" in prompt
    assert "correct option" in prompt
    assert "Coding problem" in prompt
    assert "complete runnable solution" in prompt
    assert "time and space complexity" in prompt
    assert "no clear question was detected" in prompt
    assert "Which data structure uses FIFO?" in prompt