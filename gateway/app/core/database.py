from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = "sqlite:////app/data/chalchitra.db"
engine = create_engine(DATABASE_URL)

def create_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session