from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")

DEMO_MANAGER = {"name": "Коваленко І.", "role": "Менеджер"}
DEMO_CASHIER = {"name": "Шевченко М.", "role": "Касир"}


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"user": None})


@router.get("/manager", response_class=HTMLResponse)
def manager_page(request: Request):
    return templates.TemplateResponse(request, "manager.html", {"user": DEMO_MANAGER})


@router.get("/cashier", response_class=HTMLResponse)
def cashier_page(request: Request):
    return templates.TemplateResponse(request, "manager.html", {"user": DEMO_CASHIER})