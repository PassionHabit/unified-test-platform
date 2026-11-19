"""/api/v1/projects：项目与 Profile 自服务管理。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Department, ExecutionProfile, Project
from ...schemas import ProfileCreate, ProfileOut, ProjectCreate, ProjectOut

router = APIRouter(tags=["projects"])


def _get_project_or_404(db: Session, name: str) -> Project:
    project = db.execute(select(Project).where(Project.name == name)).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail=f"project '{name}' not found")
    return project


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    exists = db.execute(select(Project).where(Project.name == body.name)).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail=f"project '{body.name}' already exists")

    department_id = body.department_id
    if department_id is None:
        department = db.execute(select(Department).where(Department.name == "default")).scalar_one_or_none()
        if department is None:
            raise HTTPException(status_code=500, detail="default department missing (run migrations)")
        department_id = department.id

    project = Project(
        name=body.name,
        department_id=department_id,
        source_type=body.source_type,
        repository_ref=body.repository_ref,
        owner=body.owner,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)) -> list[Project]:
    limit = max(1, min(limit, 200))
    stmt = select(Project).order_by(Project.id).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars())


@router.get("/projects/{name}", response_model=ProjectOut)
def get_project(name: str, db: Session = Depends(get_db)) -> Project:
    return _get_project_or_404(db, name)


@router.post("/projects/{name}/profiles", response_model=ProfileOut, status_code=201)
def create_profile(name: str, body: ProfileCreate, db: Session = Depends(get_db)) -> ExecutionProfile:
    project = _get_project_or_404(db, name)
    exists = db.execute(
        select(ExecutionProfile).where(
            ExecutionProfile.project_id == project.id,
            ExecutionProfile.name == body.name,
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail=f"profile '{body.name}' already exists")

    profile = ExecutionProfile(
        project_id=project.id,
        name=body.name,
        revision=1,
        runtime_image_ref=body.runtime_image_ref,
        prepare_spec=(
            {"argv": body.prepare_argv, "timeout_s": body.prepare_timeout_s}
            if body.prepare_argv
            else None
        ),
        command_template={"argv": body.argv},
        parameter_schema=body.parameter_schema,
        resource_spec=body.resources,
        artifact_spec=body.artifacts,
        service_bindings=body.service_bindings,
        timeout_default=body.timeout_default,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/projects/{name}/profiles", response_model=list[ProfileOut])
def list_profiles(name: str, db: Session = Depends(get_db)) -> list[ExecutionProfile]:
    project = _get_project_or_404(db, name)
    stmt = select(ExecutionProfile).where(ExecutionProfile.project_id == project.id)
    return list(db.execute(stmt).scalars())
