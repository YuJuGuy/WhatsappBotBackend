from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db.engine import create_db_and_tables
from app.api.auth import routes as auth_routes
from app.api.users import routes as user_routes
from app.api.phone import routes as phone_routes

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(lifespan=lifespan)

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

@app.get("/")
def read_root():
    return {"message": "Welcome to FastAPI NextJS Auth API"}

