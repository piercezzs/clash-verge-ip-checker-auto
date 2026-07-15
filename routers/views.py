from __future__ import annotations

from inspect import signature

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os

router = APIRouter()

templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
templates = Jinja2Templates(directory=templates_dir)


def render_template(request: Request, name: str, context: dict[str, object] | None = None) -> HTMLResponse:
    template_context = context or {}
    parameters = list(signature(templates.TemplateResponse).parameters)

    if parameters[:2] == ["request", "name"]:
        return templates.TemplateResponse(request, name, template_context)

    return templates.TemplateResponse(name, {**template_context, "request": request})


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render main page"""
    return render_template(request, "index.html")
