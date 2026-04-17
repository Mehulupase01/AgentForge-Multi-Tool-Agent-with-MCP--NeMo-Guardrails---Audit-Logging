from __future__ import annotations

import asyncio
from pathlib import Path

import click

from agentforge.database import get_session_factory, init_engine
from agentforge.services.redteam_service import get_redteam_runner


@click.command("redteam-run")
@click.option("--scenario-id", "scenario_ids", multiple=True, help="Run only selected scenario ids.")
def run_redteam_command(scenario_ids: tuple[str, ...]) -> None:
    """Run the red-team suite and write a JUnit XML report."""

    async def _run() -> None:
        init_engine()
        runner = get_redteam_runner(session_factory=get_session_factory())
        run = await runner.run(list(scenario_ids) or None)
        report_path = await runner.write_junit_report(run.id, output_path=Path("redteam-report.xml"))
        if run.safety_compliance_pct < runner._threshold_pct:
            raise click.ClickException(
                f"Safety compliance {run.safety_compliance_pct:.2f}% is below the required threshold "
                f"of {runner._threshold_pct:.2f}%."
            )
        click.echo(
            f"redteam run={run.id} total={run.total_scenarios} passed={run.passed} failed={run.failed} "
            f"compliance={run.safety_compliance_pct:.2f}% report={report_path}"
        )

    asyncio.run(_run())
