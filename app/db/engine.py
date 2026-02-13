from sqlmodel import SQLModel, create_engine, Session
from app.models.user import User
from app.models.phone import Phone
from app.models.group import Group
from app.models.phone_group_link import PhoneGroupLink

sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, echo=False, connect_args=connect_args)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
