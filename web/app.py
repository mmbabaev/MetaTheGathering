from fastapi import FastAPI

from web.routes import auth, me, settings, tournaments

app = FastAPI(title="MetaGatherer Web", docs_url=None, redoc_url=None)

app.include_router(auth.router)
app.include_router(tournaments.router)
app.include_router(me.router)
app.include_router(settings.router)
