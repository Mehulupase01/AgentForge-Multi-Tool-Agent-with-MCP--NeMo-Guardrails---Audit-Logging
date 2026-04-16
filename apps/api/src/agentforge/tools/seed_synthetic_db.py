from __future__ import annotations

import random
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import click
from faker import Faker

REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_OUTPUT_PATH = REPO_ROOT / "fixtures" / "synthetic.sqlite"
SEED = 20260416

DEPARTMENTS = ["engineering", "marketing", "finance", "hr", "ops"]
ROLES_BY_DEPARTMENT = {
    "engineering": ["Software Engineer", "Platform Engineer", "Data Engineer", "ML Engineer"],
    "marketing": ["Growth Manager", "Content Strategist", "Campaign Analyst", "Brand Lead"],
    "finance": ["Financial Analyst", "Controller", "Procurement Specialist", "FP&A Manager"],
    "hr": ["People Partner", "Recruiter", "Talent Programs Lead", "HR Operations Specialist"],
    "ops": ["Operations Manager", "Support Lead", "Program Manager", "Business Operations Analyst"],
}
PROJECT_STATUSES = ["planning", "active", "on_hold", "completed", "cancelled"]
PROJECT_ROLES = ["owner", "tech_lead", "analyst", "contributor", "reviewer"]
PROJECT_NAMES = [
    "Atlas Insights Hub",
    "Beacon Forecast Engine",
    "Compass Workflow Upgrade",
    "Delta Risk Dashboard",
    "Echo Support Automation",
    "Flux Data Platform",
    "Galaxy Reporting Revamp",
    "Harbor Compliance Portal",
    "Ion Collaboration Suite",
    "Juno Pricing Optimizer",
    "Keystone Search Initiative",
    "Lumen Knowledge Base",
    "Meridian Planning Workspace",
    "Nimbus Operations Center",
    "Orchid Employee Experience",
    "Pulse Incident Triage",
    "Quasar Metrics Pipeline",
    "Radiant Customer Signals",
    "Summit Workforce Planner",
    "Tidal Procurement Review",
    "Umbra Security Findings",
    "Vector Delivery Tracker",
    "Waypoint Forecast Studio",
    "Xenon Finance Cockpit",
    "Yield Growth Experiments",
    "Zenith Analytics Console",
    "Aurora Collaboration Pilot",
    "Bridge Vendor Intelligence",
    "Circuit Process Automation",
    "Drift Quality Review",
]


@dataclass(slots=True)
class SeedSummary:
    output_path: Path
    employees: int
    projects: int
    assignments: int


def resolve_output_path(raw_output: Path | None = None) -> Path:
    path = raw_output or DEFAULT_OUTPUT_PATH
    return path if path.is_absolute() else REPO_ROOT / path


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", ".", value.lower()).strip(".")


def seed_synthetic_db(raw_output: Path | None = None) -> SeedSummary:
    output_path = resolve_output_path(raw_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    Faker.seed(SEED)
    fake = Faker()
    rng = random.Random(SEED)
    employees: list[dict[str, str | int]] = []

    for index in range(200):
        department = DEPARTMENTS[index % len(DEPARTMENTS)]
        name = fake.name()
        email_local = f"{slugify(name)}.{index:03d}"
        employees.append(
            {
                "id": str(uuid4()),
                "name": name,
                "email": f"{email_local}@example.com",
                "department": department,
                "role": rng.choice(ROLES_BY_DEPARTMENT[department]),
                "hire_date": (date(2018, 1, 1) + timedelta(days=index * 11)).isoformat(),
                "salary_band": (index % 7) + 1,
            }
        )

    projects: list[dict[str, str | int | None]] = []
    assignments: list[tuple[str, str, str]] = []

    for index, project_name in enumerate(PROJECT_NAMES):
        owner = employees[(index * 7) % len(employees)]
        status = PROJECT_STATUSES[index % len(PROJECT_STATUSES)]
        start_date = date(2024, 1, 1) + timedelta(days=index * 14)
        completed = status in {"completed", "cancelled"}
        project_id = str(uuid4())
        projects.append(
            {
                "id": project_id,
                "name": project_name,
                "owner_employee_id": owner["id"],
                "status": status,
                "budget_eur": 120000 + (index * 17500),
                "start_date": start_date.isoformat(),
                "end_date": (start_date + timedelta(days=180)).isoformat() if completed else None,
            }
        )

        assigned_indices = {(index * 7) % len(employees)}
        while len(assigned_indices) < 20:
            assigned_indices.add(rng.randrange(len(employees)))

        ordered_indices = list(assigned_indices)
        for assignment_index, employee_index in enumerate(ordered_indices):
            assignments.append(
                (
                    project_id,
                    employees[employee_index]["id"],
                    PROJECT_ROLES[assignment_index % len(PROJECT_ROLES)],
                ),
            )

    connection = sqlite3.connect(output_path)
    try:
        cursor = connection.cursor()
        cursor.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE employees (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              email TEXT NOT NULL UNIQUE,
              department TEXT NOT NULL,
              role TEXT NOT NULL,
              hire_date TEXT NOT NULL,
              salary_band INTEGER NOT NULL CHECK (salary_band BETWEEN 1 AND 7)
            );
            CREATE INDEX ix_employees_department ON employees(department);

            CREATE TABLE projects (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              owner_employee_id TEXT NOT NULL REFERENCES employees(id),
              status TEXT NOT NULL CHECK (status IN ('planning','active','on_hold','completed','cancelled')),
              budget_eur INTEGER NOT NULL,
              start_date TEXT NOT NULL,
              end_date TEXT
            );
            CREATE INDEX ix_projects_status ON projects(status);

            CREATE TABLE project_assignments (
              project_id TEXT NOT NULL REFERENCES projects(id),
              employee_id TEXT NOT NULL REFERENCES employees(id),
              role_on_project TEXT NOT NULL,
              PRIMARY KEY (project_id, employee_id)
            );
            """
        )

        cursor.executemany(
            """
            INSERT INTO employees (id, name, email, department, role, hire_date, salary_band)
            VALUES (:id, :name, :email, :department, :role, :hire_date, :salary_band)
            """,
            employees,
        )
        cursor.executemany(
            """
            INSERT INTO projects (id, name, owner_employee_id, status, budget_eur, start_date, end_date)
            VALUES (:id, :name, :owner_employee_id, :status, :budget_eur, :start_date, :end_date)
            """,
            projects,
        )
        cursor.executemany(
            """
            INSERT INTO project_assignments (project_id, employee_id, role_on_project)
            VALUES (?, ?, ?)
            """,
            assignments,
        )
        connection.commit()
    finally:
        connection.close()

    return SeedSummary(
        output_path=output_path,
        employees=len(employees),
        projects=len(projects),
        assignments=len(assignments),
    )


@click.command("seed-synthetic")
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=DEFAULT_OUTPUT_PATH,
    show_default=True,
)
def seed_synthetic_command(output: Path) -> None:
    summary = seed_synthetic_db(output)
    click.echo(
        f"Seeded synthetic database at {summary.output_path} "
        f"(employees={summary.employees}, projects={summary.projects}, assignments={summary.assignments})",
    )


if __name__ == "__main__":
    seed_synthetic_command()
