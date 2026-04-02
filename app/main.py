from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db.engine import create_db_and_tables
from app.api.auth import routes as auth_routes
from app.api.users import routes as user_routes
from app.api.phone import routes as phone_routes
from app.api.settings import routes as settings_routes
from app.api.templates import routes as template_routes
from app.api.campaigns import routes as campaign_routes
from app.api.calls import routes as call_routes
from app.api.webhooks import routes as webhook_routes
from app.api.autoreply import routes as autoreply_routes
from app.api.messages import routes as messages_routes
from app.api.blacklist import routes as blacklist_routes
from app.api.train import routes as train_routes
from app.api.storage import routes as storage_routes
from app.api.flow import routes as flow_routes
from app.api.dashboard import routes as dashboard_routes
from app.api.tickets import routes as tickets_routes

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

from fastapi.middleware.cors import CORSMiddleware

origins = [
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_routes.router, prefix="/api/auth", tags=["auth"])
app.include_router(user_routes.router, prefix="/api/users", tags=["users"])
app.include_router(phone_routes.router, prefix="/api/phone", tags=["phone"])
app.include_router(settings_routes.router, prefix="/api/settings", tags=["settings"])
app.include_router(template_routes.router, prefix="/api/templates", tags=["templates"])
app.include_router(campaign_routes.router, prefix="/api/campaigns", tags=["campaigns"])
app.include_router(call_routes.router, prefix="/api/calls-config", tags=["calls-config"])
app.include_router(webhook_routes.router, prefix="/api/webhook", tags=["webhook"])
app.include_router(autoreply_routes.router, prefix="/api/autoreply", tags=["autoreply"])
app.include_router(messages_routes.router, prefix="/api/messages", tags=["messages"])
app.include_router(blacklist_routes.router, prefix="/api/blacklist", tags=["blacklist"])
app.include_router(train_routes.router, prefix="/api/train", tags=["train"])
app.include_router(storage_routes.router, prefix="/api/storage", tags=["storage"])
app.include_router(flow_routes.router, prefix="/api/flow", tags=["flow"])
app.include_router(dashboard_routes.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(tickets_routes.router, prefix="/api/tickets", tags=["tickets"])

@app.get("/")
def read_root():
    return {"message": "Welcome to WhataBot API"}
