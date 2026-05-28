"""Playwright-based browser automation for filling job application forms."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import structlog
from playwright.async_api import Page, async_playwright

from src.appliers.base import BaseApplier
from src.models import ApplicationResult, Job, StructuredResume, TailoredOutput
from src.tailoring.question_answerer import ATSQuestion, QuestionAnswerer

# Imported lazily to avoid circular imports — used only for _match_option_id helper
def _match_option(question, answer):  # type: ignore[no-untyped-def]
    from src.appliers.greenhouse_api import GreenhouseAPIApplier
    return GreenhouseAPIApplier._match_option_id(question, answer)

log = structlog.get_logger()

# Job listing platforms that require login — can't apply via browser without auth
_LISTING_DOMAINS = (
    "linkedin.com/jobs/",
    "indeed.com/viewjob",
    "glassdoor.com/job-listing",
    "glassdoor.com/Jobs",
)

# Maps profile fields to common form field patterns (label, name, id, placeholder)
FIELD_PATTERNS: dict[str, list[str]] = {
    "first_name": [r"first.?name", r"fname", r"given.?name"],
    "last_name": [r"last.?name", r"lname", r"surname", r"family.?name"],
    "email": [r"e?-?mail"],
    "phone": [r"phone", r"mobile", r"tel(?:ephone)?"],
    "linkedin_url": [r"linked.?in"],
    "website": [r"website", r"portfolio", r"personal.?(?:site|url|page)"],
    "github": [r"github"],
    "current_company": [r"current.?(?:company|employer|org)"],
    "current_title": [r"current.?(?:title|role|position)"],
    "location": [r"(?:city|location|address)"],
}


class BrowserApplier(BaseApplier):
    def __init__(
        self,
        dry_run: bool = False,
        question_answerer: QuestionAnswerer | None = None,
    ):
        self.dry_run = dry_run
        self.question_answerer = question_answerer

    def can_handle(self, job: Job) -> bool:
        # Skip job listing URLs that require authentication
        if not job.apply_url:
            return False
        url = job.apply_url.lower()
        if any(domain in url for domain in _LISTING_DOMAINS):
            return False
        return True

    async def apply(
        self,
        job: Job,
        tailored: TailoredOutput,
        user_profile: dict,
        resume: StructuredResume | None = None,
    ) -> ApplicationResult:
        log.info(
            "browser_applying",
            job_id=job.id,
            company=job.company,
            url=job.apply_url,
            dry_run=self.dry_run,
        )

        screenshots_dir = Path("output/screenshots")
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                )
                page = await context.new_page()

                # Navigate to apply URL
                await page.goto(job.apply_url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(2)  # Wait for JS rendering
                await page.screenshot(
                    path=str(screenshots_dir / f"{job.id}_01_initial.png")
                )

                # Fill form fields
                filled = await self._fill_form_fields(page, user_profile)
                log.info("browser_fields_filled", job_id=job.id, fields_filled=filled)

                # Answer mandatory questions
                if self.question_answerer and resume:
                    await self._answer_form_questions(page, job, resume)

                # Upload resume
                resume_uploaded = await self._upload_file(
                    page, tailored.resume_pdf_path, ["resume", "cv", "curriculum"]
                )

                # Upload cover letter
                cl_uploaded = await self._upload_file(
                    page, tailored.cover_letter_pdf_path, ["cover.?letter"]
                )

                await page.screenshot(
                    path=str(screenshots_dir / f"{job.id}_02_filled.png")
                )

                if self.dry_run:
                    log.info("browser_dry_run_complete", job_id=job.id)
                    await browser.close()
                    return ApplicationResult(
                        success=True,
                        response_data={
                            "dry_run": True,
                            "fields_filled": filled,
                            "resume_uploaded": resume_uploaded,
                            "cover_letter_uploaded": cl_uploaded,
                        },
                    )

                # Submit
                submitted = await self._click_submit(page)
                await asyncio.sleep(3)
                await page.screenshot(
                    path=str(screenshots_dir / f"{job.id}_03_submitted.png")
                )

                await browser.close()

                if submitted:
                    return ApplicationResult(success=True)
                else:
                    return ApplicationResult(
                        success=False, error="Could not find submit button"
                    )

        except Exception as e:
            log.error("browser_apply_error", job_id=job.id, error=str(e))
            return ApplicationResult(success=False, error=str(e))

    async def _fill_form_fields(self, page: Page, profile: dict) -> list[str]:
        """Detect and fill form fields matching the user profile."""
        filled: list[str] = []

        for field_name, patterns in FIELD_PATTERNS.items():
            value = profile.get(field_name, "")
            if not value:
                continue

            for pattern in patterns:
                # Try finding by label
                try:
                    label = page.locator(f"label:text-matches('{pattern}', 'i')")
                    if await label.count() > 0:
                        for_attr = await label.first.get_attribute("for")
                        if for_attr:
                            input_el = page.locator(f"#{for_attr}")
                            if await input_el.count() > 0:
                                await input_el.fill(str(value))
                                filled.append(field_name)
                                break
                except Exception:
                    pass

                # Try finding by input name/id/placeholder attributes
                for attr in ["name", "id", "placeholder"]:
                    try:
                        selector = f"input[{attr}]:visible"
                        inputs = page.locator(selector)
                        count = await inputs.count()
                        for i in range(count):
                            el = inputs.nth(i)
                            attr_val = await el.get_attribute(attr) or ""
                            if re.search(pattern, attr_val, re.IGNORECASE):
                                await el.fill(str(value))
                                filled.append(field_name)
                                break
                        if field_name in filled:
                            break
                    except Exception:
                        continue

                if field_name in filled:
                    break

        return filled

    async def _answer_form_questions(
        self, page: Page, job: Job, resume: StructuredResume
    ) -> None:
        """Detect and answer textarea, text input, and select dropdown questions."""
        try:
            flat_profile_patterns = [
                p for plist in FIELD_PATTERNS.values() for p in plist
            ]

            questions: list[ATSQuestion] = []

            # --- textareas ---
            textareas = page.locator("textarea:visible")
            count = await textareas.count()
            for i in range(count):
                el = textareas.nth(i)
                q_id = (
                    await el.get_attribute("id")
                    or await el.get_attribute("name")
                    or f"ta_{i}"
                )
                label_text = await self._find_label_for(page, q_id)
                if label_text and not any(
                    re.search(p, label_text, re.IGNORECASE) for p in flat_profile_patterns
                ):
                    questions.append(
                        ATSQuestion(question_id=q_id, label=label_text,
                                    required=True, field_type="textarea")
                    )

            # --- required text inputs not yet filled ---
            required_inputs = page.locator(
                "input[type='text'][required]:visible, "
                "input[type='text'][aria-required='true']:visible"
            )
            count = await required_inputs.count()
            for i in range(count):
                el = required_inputs.nth(i)
                q_id = (
                    await el.get_attribute("id")
                    or await el.get_attribute("name")
                    or f"inp_{i}"
                )
                if await el.input_value():
                    continue
                label_text = await self._find_label_for(page, q_id)
                if label_text and not any(
                    re.search(p, label_text, re.IGNORECASE) for p in flat_profile_patterns
                ):
                    questions.append(
                        ATSQuestion(question_id=q_id, label=label_text,
                                    required=True, field_type="input_text")
                    )

            # --- select dropdowns (the key missing piece) ---
            selects = page.locator("select:visible")
            count = await selects.count()
            for i in range(count):
                el = selects.nth(i)
                q_id = (
                    await el.get_attribute("id")
                    or await el.get_attribute("name")
                    or f"sel_{i}"
                )
                # Skip if already has a non-placeholder selection
                current = await el.input_value()
                if current and current not in ("", "0", "Select..."):
                    continue
                label_text = await self._find_label_for(page, q_id)
                if not label_text:
                    label_text = await self._find_nearby_label(page, el)
                if not label_text:
                    continue
                # Collect option labels for Claude to choose from
                option_els = el.locator("option")
                opt_count = await option_els.count()
                values: list[dict] = []
                for j in range(opt_count):
                    opt = option_els.nth(j)
                    opt_val = await opt.get_attribute("value") or ""
                    opt_label = (await opt.inner_text()).strip()
                    if opt_val and opt_label and opt_label.lower() not in (
                        "select...", "please select", "--", ""
                    ):
                        values.append({"id": opt_val, "label": opt_label})
                if values:
                    questions.append(
                        ATSQuestion(question_id=q_id, label=label_text,
                                    required=True, field_type="multi_value_single_select",
                                    values=values)
                    )

            if not questions:
                return

            log.info("browser_questions_found", job_id=job.id, count=len(questions))
            answers = await self.question_answerer.answer(questions, resume, job)

            for q in questions:
                answer = answers.get(q.question_id, "")
                if not answer:
                    continue
                try:
                    if q.field_type == "textarea":
                        await page.locator(
                            f"textarea#{q.question_id}, textarea[name='{q.question_id}']"
                        ).first.fill(answer)
                    elif q.field_type == "multi_value_single_select":
                        # Select by value (option id) first, fall back to label text
                        sel = page.locator(
                            f"select#{q.question_id}, select[name='{q.question_id}']"
                        ).first
                        matched = _match_option(q, answer) if q.values else None
                        if matched:
                            await sel.select_option(value=matched)
                        else:
                            await sel.select_option(label=re.compile(re.escape(answer[:10]), re.I))
                    else:
                        await page.locator(
                            f"input#{q.question_id}, input[name='{q.question_id}']"
                        ).first.fill(answer)
                    log.debug("browser_question_filled", question_id=q.question_id, label=q.label)
                except Exception as e:
                    log.warning("browser_question_fill_failed",
                                question_id=q.question_id, label=q.label, error=str(e))

        except Exception as e:
            log.warning("browser_answer_questions_failed", job_id=job.id, error=str(e))

    @staticmethod
    async def _find_nearby_label(page: Page, el) -> str:
        """Find label text near a select element (preceding sibling or parent label)."""
        try:
            # Try aria-label attribute
            aria = await el.get_attribute("aria-label") or ""
            if aria:
                return aria.strip()
            # Try preceding label/legend text via JS
            text = await page.evaluate("""el => {
                const prev = el.previousElementSibling;
                if (prev) return prev.textContent.trim();
                const parent = el.parentElement;
                if (parent) {
                    const label = parent.querySelector('label');
                    if (label) return label.textContent.trim();
                }
                return '';
            }""", await el.element_handle())
            return (text or "").strip()
        except Exception:
            return ""

    @staticmethod
    async def _find_label_for(page: Page, element_id: str) -> str:
        """Find the label text for a given element id or name."""
        try:
            label = page.locator(f"label[for='{element_id}']")
            if await label.count() > 0:
                return (await label.first.inner_text()).strip()
        except Exception:
            pass
        return ""

    async def _upload_file(
        self, page: Page, file_path: str, patterns: list[str]
    ) -> bool:
        """Find a file input and upload a file."""
        if not file_path or not Path(file_path).exists():
            return False

        try:
            file_inputs = page.locator("input[type='file']")
            count = await file_inputs.count()

            for i in range(count):
                el = file_inputs.nth(i)
                # Check name, id, aria-label, and nearby label text
                for attr in ["name", "id", "aria-label", "accept"]:
                    attr_val = await el.get_attribute(attr) or ""
                    for pattern in patterns:
                        if re.search(pattern, attr_val, re.IGNORECASE):
                            await el.set_input_files(file_path)
                            log.info("file_uploaded", path=file_path, field=attr_val)
                            return True

            # Fallback: if only one file input exists, use it for resume
            if count == 1 and "resume" in str(patterns):
                await file_inputs.first.set_input_files(file_path)
                log.info("file_uploaded_fallback", path=file_path)
                return True

        except Exception as e:
            log.warning("file_upload_error", error=str(e))

        return False

    async def _click_submit(self, page: Page) -> bool:
        """Find and click the submit button, then verify no validation errors remain."""
        submit_patterns = [
            "button[type='submit']",
            "input[type='submit']",
            "button:text-matches('submit|apply|send', 'i')",
            "a:text-matches('submit|apply now', 'i')",
        ]

        clicked = False
        for selector in submit_patterns:
            try:
                el = page.locator(selector)
                if await el.count() > 0:
                    await el.first.click()
                    log.info("submit_clicked", selector=selector)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            return False

        # Wait for page response
        await asyncio.sleep(3)

        # Check for validation error indicators — means submission was rejected
        error_indicators = [
            "text='This field is required'",
            "text='is required'",
            "[aria-invalid='true']",
            ".error:visible",
            ".field-error:visible",
            "[data-error]:visible",
        ]
        for indicator in error_indicators:
            try:
                if await page.locator(indicator).count() > 0:
                    log.warning("submit_validation_errors_detected", indicator=indicator)
                    return False
            except Exception:
                pass

        # Check for success signals
        success_patterns = [
            "text='thank you'",
            "text='application submitted'",
            "text='application received'",
            "text='successfully submitted'",
            "text='we\\'ll be in touch'",
        ]
        for pattern in success_patterns:
            try:
                if await page.locator(pattern).count() > 0:
                    log.info("submit_success_confirmed", pattern=pattern)
                    return True
            except Exception:
                pass

        # If URL changed away from the apply form, likely successful
        current_url = page.url
        if "confirmation" in current_url or "thank" in current_url or "success" in current_url:
            return True

        # No errors detected — treat as success (form may have redirected)
        return True
