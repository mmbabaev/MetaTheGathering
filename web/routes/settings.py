from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from web.auth import get_current_user, get_db
from web.templating import templates

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user=Depends(get_current_user)):
    return templates.TemplateResponse("settings.html", {"request": request, "user": user})


@router.post("/settings")
async def settings_save(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
    display_name: str = Form(...),
):
    display_name = display_name.strip()
    if display_name:
        user.display_name = display_name
        db.commit()
    return RedirectResponse("/", status_code=303)
