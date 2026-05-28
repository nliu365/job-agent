"""Parse Word/PDF resumes into structured JSON using Claude API."""

from __future__ import annotations

from pathlib import Path

import anthropic

from src.models import StructuredResume

PARSE_PROMPT = """Parse this resume into structured JSON. Return ONLY valid JSON with this exact schema:
{
  "name": "Full Name",
  "email": "email@example.com",
  "phone": "+1-555-555-5555",
  "linkedin_url": "https://linkedin.com/in/...",
  "location": "City, State",
  "summary": "Professional summary paragraph",
  "experience": [
    {
      "company": "Company Name",
      "title": "Job Title",
      "start_date": "Jan 2020",
      "end_date": "Present",
      "bullets": ["Accomplishment 1", "Accomplishment 2"]
    }
  ],
  "education": [
    {
      "school": "University Name",
      "degree": "Degree Type",
      "field": "Field of Study",
      "start_date": "2012",
      "end_date": "2016",
      "gpa": null
    }
  ],
  "skills": ["Skill 1", "Skill 2"],
  "certifications": [],
  "publications": []
}

Resume text:
"""


def extract_text_from_docx(file_path: str) -> str:
    """Extract text from a Word document."""
    import docx

    doc = docx.Document(file_path)
    paragraphs = []
    for para in doc.paragraphs:
        if para.text.strip():
            paragraphs.append(para.text.strip())
    return "\n".join(paragraphs)


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from a PDF document."""
    import fitz  # pymupdf

    doc = fitz.open(file_path)
    text_parts = []
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()
    return "\n".join(text_parts)


def extract_text(file_path: str) -> str:
    """Extract text from a resume file (PDF or DOCX)."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".docx":
        return extract_text_from_docx(file_path)
    elif suffix == ".pdf":
        return extract_text_from_pdf(file_path)
    elif suffix == ".txt":
        return path.read_text(encoding="utf-8")
    else:
        raise ValueError(f"Unsupported file format: {suffix}. Use .pdf, .docx, or .txt")


def parse_resume(file_path: str, api_key: str) -> StructuredResume:
    """Parse a resume file into a StructuredResume using Claude API."""
    raw_text = extract_text(file_path)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": PARSE_PROMPT + raw_text,
            }
        ],
    )

    response_text = response.content[0].text

    # Extract JSON from response (handle markdown code blocks)
    json_text = response_text
    if "```json" in json_text:
        json_text = json_text.split("```json")[1].split("```")[0]
    elif "```" in json_text:
        json_text = json_text.split("```")[1].split("```")[0]

    return StructuredResume.model_validate_json(json_text.strip())
