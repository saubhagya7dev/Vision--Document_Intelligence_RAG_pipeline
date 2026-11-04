"""One opt-in real provider request over fictional pages; no user library or GPU."""

import json
import re
import tempfile
from pathlib import Path
from time import perf_counter

from phase4_corpus import pdf

from vision_rag.analysis.contracts import ComparisonRequest, validate_table
from vision_rag.config import settings
from vision_rag.ingest.document_loader import DocumentLoader
from vision_rag.models.gemini_generator import GeminiGenerator


def main():
    report = {
        "fixture": "two fictional PDF pages",
        "model": settings.generation_model_name,
        "provider_attempts": 1,
        "scope": "provider comparison adapter only; "
        "not a retrieval or broad quality benchmark",
    }
    request = ComparisonRequest(
        question="Compare reported revenue and operating margin.",
        version_ids=["fictional-alpha", "fictional-beta"],
        fields=["Revenue", "Operating margin"],
    )
    sources, images = [], []
    generator = None
    started = perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="vision-phase6-provider-") as folder:
            loader = DocumentLoader(dpi=150)
            for index, (name, value, currency, period, scope) in enumerate(
                [
                    ("alpha", "120", "EUR", "FY2024", "Consolidated"),
                    ("beta", "150", "USD", "FY2025", "Parent company"),
                ]
            ):
                lines = [
                    f"Fictional {name} report",
                    f"Revenue: {value} million {currency}",
                    f"Reporting period: {period}",
                    f"Scope: {scope}",
                    "Operating margin is not disclosed.",
                ]
                path = Path(folder) / f"{name}.pdf"
                pdf(path, [lines])
                images.append(loader.load_page(path, 1))
                sources.append(
                    {
                        "id": f"E{index + 1}",
                        "evidence_id": f"E{index + 1}",
                        "version_id": request.version_ids[index],
                        "page": 1,
                        "source": path.name,
                        "excerpt": "\n".join(lines),
                    }
                )
            generator = GeminiGenerator(
                settings.generation_model_name,
                settings.provider_api_key,
                timeout_ms=15000,
                attempts=1,
            )
            raw = generator.generate_comparison(request.model_dump(), sources, images)
            table = validate_table(raw, request, sources)
            checks = []
            for version, expected, currency, period, scope in [
                ("fictional-alpha", "120", "EUR", "FY2024", "Consolidated"),
                ("fictional-beta", "150", "USD", "FY2025", "Parent company"),
            ]:
                revenue = next(
                    c
                    for c in table.cells
                    if c.version_id == version and c.field == "Revenue"
                )
                missing = next(
                    c
                    for c in table.cells
                    if c.version_id == version and c.field == "Operating margin"
                )
                checks.append(
                    revenue.status == "reported"
                    and re.findall(r"\d+", revenue.value or "") == [expected]
                    and revenue.currency == currency
                    and revenue.period == period
                    and revenue.unit == "million"
                    and revenue.scope == scope
                    and missing.status == "missing"
                )
            report.update(
                status="passed" if all(checks) else "quality_check_failed",
                expected_value_checks=checks,
                table=table.model_dump(),
                usage=generator.last_usage,
            )
    except Exception as error:
        report.update(
            status="provider_unavailable",
            code=getattr(error, "code", None),
            error_type=type(error).__name__,
        )
    finally:
        for image in images:
            image.close()
        if generator:
            generator.close()
    report["seconds"] = perf_counter() - started
    Path("Docs/phase6-provider-smoke.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps({k: report.get(k) for k in ("status", "code", "seconds")}),
        flush=True,
    )


if __name__ == "__main__":
    main()
