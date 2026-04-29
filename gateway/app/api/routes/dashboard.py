from fastapi import APIRouter
router = APIRouter()

@router.get("/")
def dashboard():
    return {"status": "ok"}