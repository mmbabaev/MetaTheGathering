from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def user_display_name(user) -> str:
    if user.display_name:
        return user.display_name
    parts = [user.first_name or "", user.last_name or ""]
    name = " ".join(p for p in parts if p).strip()
    return name or user.username or user.email or "Игрок"


templates.env.globals["user_display_name"] = user_display_name
