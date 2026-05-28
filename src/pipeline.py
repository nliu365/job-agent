"""Main pipeline orchestration: scan -> filter -> tailor -> apply -> notify."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from src.appliers.base import BaseApplier
from src.appliers.browser_applier import BrowserApplier
from src.appliers.greenhouse_api import GreenhouseAPIApplier
from src.appliers.lever_api import LeverAPIApplier
from src.config import AppConfig, load_config
from src.filters.dedup import deduplicate_jobs
from src.filters.relevance import score_job
from src.models import ApplicationStatus, Job, StructuredResume, TailoredOutput
from src.notifications.email_notifier import EmailNotifier
from src.scanners.base import BaseScanner
from src.scanners.glassdoor import GlassdoorScanner
from src.scanners.greenhouse import GreenhouseScanner
from src.scanners.hn_hiring import HNHiringScanner
from src.scanners.indeed import IndeedScanner
from src.scanners.lever import LeverScanner
from src.scanners.linkedin import LinkedInScanner
from src.storage.application_store import ApplicationStore
from src.storage.job_store import JobStore
from src.tailoring.cover_letter import CoverLetterGenerator
from src.tailoring.pdf_renderer import PDFRenderer
from src.tailoring.question_answerer import QuestionAnswerer
from src.tailoring.resume_tailor import ResumeTailor

log = structlog.get_logger()

SCANNER_MAP: dict[str, type[BaseScanner]] = {
    "linkedin": LinkedInScanner,
    "indeed": IndeedScanner,
    "glassdoor": GlassdoorScanner,
    "greenhouse": GreenhouseScanner,
    "lever": LeverScanner,
    "hn_hiring": HNHiringScanner,
}


class Pipeline:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or load_config()
        self.job_store = JobStore(f"{self.config.data_dir}/jobs.db")
        self.app_store = ApplicationStore(f"{self.config.data_dir}/jobs.db")
        self.notifier = EmailNotifier(self.config, self.config.template_dir)
        self._resume: StructuredResume | None = None

    async def initialize(self) -> None:
        """Initialize storage and load resume."""
        await self.job_store.initialize()
        self._load_resume()

    def _load_resume(self) -> None:
        """Load the structured resume from JSON."""
        resume_path = Path(self.config.data_dir) / "resume.json"
        if resume_path.exists():
            data = json.loads(resume_path.read_text())
            self._resume = StructuredResume.model_validate(data)
            log.info("resume_loaded", name=self._resume.name)
        else:
            log.warning("resume_not_found", path=str(resume_path))

    # ──────────────────────────────────────────────
    # SCAN PHASE
    # ──────────────────────────────────────────────

    async def run_scan(self) -> list[Job]:
        """Scan all sources, filter, deduplicate, store, and notify."""
        await self.initialize()

        # Initialize enabled scanners
        scanners: list[BaseScanner] = []
        for name in self.config.scanner.enabled:
            scanner_cls = SCANNER_MAP.get(name)
            if scanner_cls:
                scanners.append(scanner_cls(self.config))
            else:
                log.warning("unknown_scanner", name=name)

        # Run all scanners concurrently
        log.info("scan_starting", scanners=[s.source.value for s in scanners])
        results = await asyncio.gather(
            *[s.scan() for s in scanners],
            return_exceptions=True,
        )

        # Collect all jobs
        all_jobs: list[Job] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                log.error(
                    "scanner_failed",
                    scanner=scanners[i].source.value,
                    error=str(result),
                )
            else:
                all_jobs.extend(result)

        log.info("scan_raw_results", total=len(all_jobs))

        # Deduplicate
        unique_jobs = deduplicate_jobs(all_jobs)
        log.info("scan_after_dedup", unique=len(unique_jobs), removed=len(all_jobs) - len(unique_jobs))

        # Score and filter
        matched_jobs: list[Job] = []
        for job in unique_jobs:
            job.relevance_score = score_job(job, self.config.search)
            if job.relevance_score >= self.config.pipeline.relevance_threshold:
                matched_jobs.append(job)

        log.info(
            "scan_after_filter",
            matched=len(matched_jobs),
            threshold=self.config.pipeline.relevance_threshold,
        )

        # Store new jobs
        new_jobs: list[Job] = []
        for job in matched_jobs:
            inserted = await self.job_store.insert_job(job)
            if inserted:
                await self.app_store.create_application(job.id, ApplicationStatus.MATCHED)
                new_jobs.append(job)

        log.info("scan_new_jobs_stored", count=len(new_jobs))

        # Notify
        if new_jobs and self.config.notification.send_on_new_matches:
            self.notifier.notify_new_matches(new_jobs)

        return new_jobs

    # ──────────────────────────────────────────────
    # APPLY PHASE
    # ──────────────────────────────────────────────

    async def run_apply(self, sources: list[str] | None = None) -> dict:
        """Tailor resumes and apply to matched jobs."""
        await self.initialize()

        if not self._resume:
            log.error("no_resume_available")
            return {"error": "No resume found. Run parse_resume.py first."}

        # Get matched jobs (Greenhouse first since they're directly applicable)
        jobs = await self.job_store.get_matched_jobs()

        # Filter by source if requested
        if sources:
            source_set = {s.lower() for s in sources}
            jobs = [j for j in jobs if j.source.value in source_set]

        if not jobs:
            log.info("no_matched_jobs_to_apply")
            return {"applied": 0, "failed": 0}

        # Limit per run
        jobs = jobs[: self.config.pipeline.max_applications_per_run]
        log.info("apply_starting", count=len(jobs))

        # Initialize appliers and tailor modules
        tailor = ResumeTailor(self.config.claude_api_key)
        cover_gen = CoverLetterGenerator(self.config.claude_api_key)
        renderer = PDFRenderer(self.config.template_dir)
        question_answerer = QuestionAnswerer(self.config.claude_api_key)

        appliers = self._build_appliers(question_answerer)
        user_profile = self.config.user_profile.model_dump()

        applied: list[dict] = []
        failed: list[dict] = []

        for job in jobs:
            try:
                result = await self._process_application(
                    job, tailor, cover_gen, renderer, appliers, user_profile, self._resume
                )
                if result["success"]:
                    applied.append(result)
                else:
                    failed.append(result)
            except Exception as e:
                log.error("application_error", job_id=job.id, error=str(e))
                failed.append({"job": job, "error": str(e)})

            # Rate limit between applications (skip delay in dry-run)
            if not self.config.pipeline.dry_run:
                await asyncio.sleep(self.config.pipeline.delay_between_applications_seconds)

        # Notify
        if self.config.notification.send_on_application:
            self.notifier.notify_applications(applied, failed)

        summary = {"applied": len(applied), "failed": len(failed)}
        log.info("apply_complete", **summary)
        return summary

    async def _process_application(
        self,
        job: Job,
        tailor: ResumeTailor,
        cover_gen: CoverLetterGenerator,
        renderer: PDFRenderer,
        appliers: list[BaseApplier],
        user_profile: dict,
        resume: StructuredResume | None = None,
    ) -> dict:
        """Process a single job application: tailor -> render -> apply."""
        app = await self.app_store.get_application_for_job(job.id)
        app_id = app["id"] if app else await self.app_store.create_application(
            job.id, ApplicationStatus.TAILORING
        )

        await self.app_store.update_status(app_id, ApplicationStatus.TAILORING)

        # Tailor resume
        tailored_resume = await tailor.tailor(self._resume, job)

        # Generate cover letter
        cover_letter = await cover_gen.generate(tailored_resume, job)

        # Render PDFs
        output_dir = Path(self.config.output_dir) / job.id
        output_dir.mkdir(parents=True, exist_ok=True)

        resume_path = renderer.render_resume(
            tailored_resume, str(output_dir / "resume.pdf")
        )
        cl_path = renderer.render_cover_letter(
            cover_letter, tailored_resume, str(output_dir / "cover_letter.pdf")
        )

        await self.app_store.set_tailored_paths(app_id, resume_path, cl_path)

        tailored_output = TailoredOutput(
            job_id=job.id,
            tailored_resume=tailored_resume,
            cover_letter=cover_letter,
            resume_pdf_path=resume_path,
            cover_letter_pdf_path=cl_path,
        )

        await self.app_store.update_status(app_id, ApplicationStatus.READY_TO_APPLY)

        # Find an applier that can handle this job
        applier = next((a for a in appliers if a.can_handle(job)), None)
        if not applier:
            log.warning("no_applier_available", job_id=job.id)
            await self.app_store.update_status(
                app_id, ApplicationStatus.SKIPPED, "No suitable applier"
            )
            return {"job": job, "success": False, "error": "No suitable applier"}

        # Apply (pass resume so appliers can answer mandatory questions)
        result = await applier.apply(job, tailored_output, user_profile, resume)

        if result.success:
            await self.app_store.update_status(app_id, ApplicationStatus.APPLIED)
        else:
            await self.app_store.update_status(
                app_id, ApplicationStatus.FAILED, result.error
            )

        return {
            "job": job,
            "success": result.success,
            "error": result.error,
            "application_id": result.application_id,
        }

    def _build_appliers(
        self, question_answerer: QuestionAnswerer | None = None
    ) -> list[BaseApplier]:
        """Build the list of appliers in priority order."""
        appliers: list[BaseApplier] = []

        # API-based appliers first (more reliable)
        if self.config.greenhouse_api_key:
            appliers.append(
                GreenhouseAPIApplier(
                    self.config.greenhouse_api_key,
                    question_answerer=question_answerer,
                )
            )
        if self.config.lever_api_key:
            appliers.append(LeverAPIApplier(self.config.lever_api_key))

        # Browser automation as fallback
        appliers.append(
            BrowserApplier(
                dry_run=self.config.pipeline.dry_run,
                question_answerer=question_answerer,
            )
        )

        return appliers

    # ──────────────────────────────────────────────
    # FULL PIPELINE
    # ──────────────────────────────────────────────

    async def run_full(self) -> dict:
        """Run both scan and apply phases."""
        new_jobs = await self.run_scan()
        apply_results = await self.run_apply()
        return {
            "new_jobs_found": len(new_jobs),
            **apply_results,
        }
