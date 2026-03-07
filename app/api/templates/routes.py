from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select
from app.schemas.template import TemplateCreate, TemplateUpdate, TemplateRead
from app.schemas.template import TemplateGroupCreate, TemplateGroupUpdate, TemplateGroupRead
from app.api.deps import get_session, get_current_user
from app.models.template import Template, TemplateGroup, TemplateGroupLink
from app.models.user import User

router = APIRouter()


# ──────────────────────────────────────────────
# Template CRUD
# ──────────────────────────────────────────────

@router.post("/", response_model=TemplateRead, status_code=status.HTTP_201_CREATED)
def create_template(
    template_in: TemplateCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new message template."""
    template = Template(
        name=template_in.name,
        body=template_in.body,
        user_id=current_user.id
    )
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


@router.get("/", response_model=List[TemplateRead])
def get_templates(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """List all templates for the current user."""
    templates = session.exec(
        select(Template).where(Template.user_id == current_user.id)
    ).all()
    return templates


@router.get("/{template_id}", response_model=TemplateRead)
def get_template(
    template_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get a single template by ID."""
    template = session.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if template.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this template")
    return template


@router.put("/{template_id}", response_model=TemplateRead)
def update_template(
    template_id: int,
    template_in: TemplateUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Update a template by ID."""
    template = session.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if template.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this template")

    if template_in.name is not None:
        template.name = template_in.name
    if template_in.body is not None:
        template.body = template_in.body

    session.add(template)
    session.commit()
    session.refresh(template)
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Delete a template by ID."""
    template = session.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if template.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this template")
    # Check if template is used in any group
    link = session.exec(select(TemplateGroupLink).where(TemplateGroupLink.template_id == template_id)).first()
    if link:
        raise HTTPException(status_code=400, detail="Template is used in a template group, Delete the template group first.")
    session.delete(template)
    session.commit()
    return None


# ──────────────────────────────────────────────
# Template Group CRUD
# ──────────────────────────────────────────────

def _build_group_response(group: TemplateGroup) -> dict:
    """Build a response dict with nested templates sorted by position."""
    templates = sorted(group.template_links, key=lambda l: l.position)
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "templates": [
            {"id": link.template.id, "name": link.template.name, "body": link.template.body}
            for link in templates
        ]
    }


def _sync_template_links(
    session: Session,
    group: TemplateGroup,
    template_ids: List[int],
    current_user_id: int
):
    """Replace all template links in a group with the given template_ids."""
    # Delete existing links
    existing_links = session.exec(
        select(TemplateGroupLink).where(TemplateGroupLink.template_group_id == group.id)
    ).all()
    for link in existing_links:
        session.delete(link)

    # Create new links
    for position, tid in enumerate(template_ids):
        template = session.get(Template, tid)
        if not template or template.user_id != current_user_id:
            raise HTTPException(
                status_code=400,
                detail=f"Template with id {tid} not found or not owned by you"
            )
        link = TemplateGroupLink(
            template_id=tid,
            template_group_id=group.id,
            position=position
        )
        session.add(link)


@router.post("/groups/", response_model=TemplateGroupRead, status_code=status.HTTP_201_CREATED)
def create_template_group(
    group_in: TemplateGroupCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new template group, optionally linking templates by ID."""
    group = TemplateGroup(
        name=group_in.name,
        description=group_in.description,
        user_id=current_user.id
    )
    session.add(group)
    session.commit()
    session.refresh(group)

    if group_in.template_ids:
        _sync_template_links(session, group, group_in.template_ids, current_user.id)
        session.commit()
        session.refresh(group)

    return _build_group_response(group)


@router.get("/groups/", response_model=List[TemplateGroupRead])
def get_template_groups(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """List all template groups for the current user, with nested templates."""
    groups = session.exec(
        select(TemplateGroup)
        .where(TemplateGroup.user_id == current_user.id)
        .options(selectinload(TemplateGroup.template_links).selectinload(TemplateGroupLink.template))
    ).all()
    return [_build_group_response(g) for g in groups]


@router.get("/groups/{group_id}", response_model=TemplateGroupRead)
def get_template_group(
    group_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get a single template group by ID with nested templates."""
    group = session.exec(
        select(TemplateGroup)
        .where(TemplateGroup.id == group_id)
        .options(selectinload(TemplateGroup.template_links).selectinload(TemplateGroupLink.template))
    ).first()
    if not group:
        raise HTTPException(status_code=404, detail="Template group not found")
    if group.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this template group")
    return _build_group_response(group)


@router.put("/groups/{group_id}", response_model=TemplateGroupRead)
def update_template_group(
    group_id: int,
    group_in: TemplateGroupUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Update a template group — name, description, and/or template list."""
    group = session.get(TemplateGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Template group not found")
    if group.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this template group")

    if group_in.name is not None:
        group.name = group_in.name
    if group_in.description is not None:
        group.description = group_in.description

    session.add(group)
    session.commit()

    if group_in.template_ids is not None:
        _sync_template_links(session, group, group_in.template_ids, current_user.id)
        session.commit()

    session.refresh(group)
    return _build_group_response(group)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template_group(
    group_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Delete a template group. Only removes the group and links, not the templates themselves."""
    group = session.get(TemplateGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Template group not found")
    if group.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this template group")

    # Delete links first
    links = session.exec(
        select(TemplateGroupLink).where(TemplateGroupLink.template_group_id == group.id)
    ).all()
    for link in links:
        session.delete(link)

    session.delete(group)
    session.commit()
    return None
