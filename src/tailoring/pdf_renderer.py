"""Render tailored resumes and cover letters to PDF using Jinja2 + WeasyPrint."""

from __future__ import annotations

from pathlib import Path

import structlog
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from src.models import StructuredResume

log = structlog.get_logger()


class PDFRenderer:
    def __init__(self, template_dir: str = "templates"):
        self.env = Environment(loader=FileSystemLoader(template_dir))

    def render_resume(self, resume: StructuredResume, output_path: str) -> str:
        """Render a tailored resume to PDF."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        template = self.env.get_template("resume.html.j2")
        html_content = template.render(resume=resume)

        css_path = Path(self.env.loader.searchpath[0]) / "resume.css"
        stylesheets = [str(css_path)] if css_path.exists() else []

        HTML(string=html_content).write_pdf(output_path, stylesheets=stylesheets)
        log.info("resume_pdf_rendered", path=output_path)
        return output_path

    def render_cover_letter(
        self,
        cover_letter_text: str,
        resume: StructuredResume,
        output_path: str,
    ) -> str:
        """Render a cover letter to PDF."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        template = self.env.get_template("cover_letter.html.j2")
        html_content = template.render(
            text=cover_letter_text,
            name=resume.name,
            email=resume.email,
            phone=resume.phone,
            linkedin_url=resume.linkedin_url,
        )

        HTML(string=html_content).write_pdf(output_path)
        log.info("cover_letter_pdf_rendered", path=output_path)
        return output_path
