from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import uuid4

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.config import get_settings
from app.schemas import AuthResponse, LoginRequest, RegisterRequest, UserResponse, UserUpdateRequest
from app.security import create_access_token, hash_password, verify_password
from app.services.avatar import generate_avatar_url

router = APIRouter(prefix='/auth', tags=['auth'])
settings = get_settings()


@router.post('/register', response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> UserResponse:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail='Email already registered')

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        target_language=(payload.target_language or '').strip() or None,
        avatar_url=generate_avatar_url(payload.email),
        is_admin=payload.email.lower() in settings.get_admin_emails(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        target_language=user.target_language,
        avatar_url=user.avatar_url,
        is_admin=bool(user.is_admin),
    )


@router.post('/login', response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail='Invalid credentials')
    should_admin = user.email.lower() in settings.get_admin_emails()
    if bool(user.is_admin) != should_admin:
        user.is_admin = should_admin
        db.add(user)
        db.commit()

    token = create_access_token(str(user.id))
    return AuthResponse(access_token=token)


@router.get('/me', response_model=UserResponse)
def me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    # Backfill avatar for old users lazily.
    if not current_user.avatar_url:
        current_user.avatar_url = generate_avatar_url(current_user.email)
        db.add(current_user)
        db.commit()
        db.refresh(current_user)
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        target_language=current_user.target_language,
        avatar_url=current_user.avatar_url,
        is_admin=bool(current_user.is_admin),
    )


@router.patch('/me', response_model=UserResponse)
def update_me(
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    if payload.display_name is not None:
        current_user.display_name = payload.display_name.strip()
    if payload.target_language is not None:
        current_user.target_language = payload.target_language.strip() or None
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        target_language=current_user.target_language,
        avatar_url=current_user.avatar_url,
        is_admin=bool(current_user.is_admin),
    )


@router.post('/me/avatar/regenerate', response_model=UserResponse)
def regenerate_avatar(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    nonce = uuid4().hex[:8]
    current_user.avatar_url = generate_avatar_url(current_user.email, nonce=nonce)
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        target_language=current_user.target_language,
        avatar_url=current_user.avatar_url,
        is_admin=bool(current_user.is_admin),
    )
