from fastapi import APIRouter, HTTPException, status
from app.models.user import LoginRequest, RegisterRequest, AuthResponse
from app.auth.jwt_handler import create_access_token
from app.db.supabase_client import get_anon_client

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest):
    try:
        client = get_anon_client()
        res = client.auth.sign_in_with_password({"email": body.email, "password": body.password})
        user = res.user
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_access_token(user_id=str(user.id), email=user.email)
        return AuthResponse(access_token=token, user_id=str(user.id), email=user.email)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail="Authentication failed") from e


@router.post("/register", response_model=AuthResponse)
def register(body: RegisterRequest):
    try:
        client = get_anon_client()
        res = client.auth.sign_up({"email": body.email, "password": body.password})
        user = res.user
        if not user:
            raise HTTPException(status_code=400, detail="Registration failed")
        token = create_access_token(user_id=str(user.id), email=user.email)
        return AuthResponse(access_token=token, user_id=str(user.id), email=user.email)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
