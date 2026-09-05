# agents/syllabus_parser_agent.py — NLP-based Syllabus Extraction
"""
Pattern: Chain-of-Thought extraction
Extracts structured topic data from uploaded syllabus PDFs/TXT files.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_llm


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text content from a PDF file."""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text.strip()
    except Exception as e:
        return f"Error reading PDF: {e}"


_OCR_ENGINE = None


def _get_ocr_engine():
    """Build the RapidOCR engine once — loading its ONNX models costs ~25s,
    so a fresh instance per image made every upload feel broken."""
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def extract_text_from_image(file_path: str) -> str:
    """Extract text from an image using on-device RapidOCR (no API key required, offline & free)."""
    try:
        engine = _get_ocr_engine()
        result, _ = engine(file_path)
        if result:
            text = "\n".join([line[1] for line in result])
            return text.strip()
        else:
            return "No text could be detected in the uploaded image. Please ensure the image is clear."
    except Exception as e:
        return f"Error extracting text from image: {e}"


def extract_text_from_file(file_path: str) -> str:
    """Extract text from PDF, TXT, or Image file."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in (".txt", ".text"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    elif ext in (".png", ".jpg", ".jpeg"):
        return extract_text_from_image(file_path)
    else:
        return f"Unsupported file type: {ext}"


def parse_syllabus(text: str, subject_name: str = "") -> dict:
    """
    Use LLM to parse syllabus text into structured JSON.
    Returns: {
        "subject_name": str,
        "units": [
            {
                "unit_name": str,
                "topics": [
                    {"topic_name": str, "description": str, "estimated_hours": float}
                ]
            }
        ]
    }
    """
    llm = get_llm(temperature=0.1, max_tokens=3000, json_mode=True)

    prompt = f"""You are an academic syllabus analyzer. Parse the following syllabus text and extract a structured breakdown.

SUBJECT: {subject_name if subject_name else "Determine from the text"}

SYLLABUS TEXT:
\"\"\"
{text[:4000]}
\"\"\"

INSTRUCTIONS:
1. Think step-by-step about the syllabus structure.
2. Identify units/modules and their topics.
3. For each topic, estimate study hours based on complexity.
4. Return ONLY valid JSON.

Return JSON in this exact format:
{{
    "subject_name": "Name of the subject",
    "reasoning": "Step-by-step analysis of how you identified the structure",
    "units": [
        {{
            "unit_name": "Unit 1: ...",
            "topics": [
                {{
                    "topic_name": "Topic name",
                    "description": "Brief description of what this topic covers",
                    "estimated_hours": 2.5
                }}
            ]
        }}
    ]
}}"""

    try:
        response = llm.invoke(prompt)
        result = json.loads(response.content)
        return result
    except json.JSONDecodeError:
        return {
            "subject_name": subject_name or "Unknown",
            "reasoning": "Failed to parse LLM response as JSON",
            "units": [],
        }
    except Exception as e:
        return {
            "subject_name": subject_name or "Unknown",
            "reasoning": f"Error: {str(e)}",
            "units": [],
        }


def parse_question_paper(text: str, subject_name: str = "") -> dict:
    """
    Parse a previous year question paper to identify important topics.
    Returns: {"important_topics": [{"topic": str, "frequency": str, "marks_weight": str}]}
    """
    llm = get_llm(temperature=0.1, max_tokens=2000, json_mode=True)

    prompt = f"""You are an exam question paper analyzer. Analyze this question paper and identify frequently tested topics.

SUBJECT: {subject_name if subject_name else "Determine from the text"}

QUESTION PAPER TEXT:
\"\"\"
{text[:4000]}
\"\"\"

INSTRUCTIONS:
1. Identify each question and its topic area.
2. Note mark allocations per topic.
3. Rank topics by importance based on marks weight and frequency.

Return JSON:
{{
    "subject_name": "{subject_name}",
    "reasoning": "Step-by-step analysis of question paper",
    "important_topics": [
        {{
            "topic": "Topic name",
            "frequency": "high/medium/low",
            "marks_weight": "percentage or marks allocated",
            "question_types": "theory/numerical/practical"
        }}
    ]
}}"""

    try:
        response = llm.invoke(prompt)
        return json.loads(response.content)
    except Exception as e:
        return {
            "subject_name": subject_name,
            "reasoning": f"Error: {str(e)}",
            "important_topics": [],
        }


def save_parsed_syllabus(parsed: dict, subject_id: int = None):
    """Save parsed syllabus data into the database."""
    from db.database import add_subject, add_topic, get_all_subjects

    # Create subject if needed
    sid = subject_id
    if not sid:
        sid = add_subject(parsed.get("subject_name", "Unknown"))

    topic_count = 0
    for unit in parsed.get("units", []):
        for topic in unit.get("topics", []):
            add_topic(
                subject_id=sid,
                topic_name=topic.get("topic_name", ""),
                unit_name=unit.get("unit_name", ""),
                description=topic.get("description", ""),
                estimated_hours=topic.get("estimated_hours", 2.0),
            )
            topic_count += 1

    return sid, topic_count
