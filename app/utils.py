from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from typing import Optional, Union
from datetime import datetime, timedelta
from io import BytesIO
import qrcode
from bson import ObjectId

from .database import get_database
from .models import User, VendorUser

# JWT settings
SECRET_KEY = "your-secret-key-here"  # In production, use environment variable
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

security = HTTPBearer()


def generate_qr_png_bytes(content: str) -> bytes:
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(content)
    qr.make(fit=True)
    # Prefer Pillow image to ensure .save(..., format="PNG") works
    try:
        from qrcode.image.pil import PilImage  # type: ignore
        img = qr.make_image(image_factory=PilImage, fill_color="black", back_color="white")
    except Exception:
        # Fallback to default factory (may be PyPNGImage)
        img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    try:
        img.save(buffer, format="PNG")
    except TypeError:
        # Some factories (e.g., PyPNGImage) don't accept the 'format' kwarg
        img.save(buffer)
    return buffer.getvalue()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.JWTError:
        return None


async def get_current_user(
    request: Request
) -> Optional[Union[User, VendorUser]]:
    # Try to get token from cookie first
    token = request.cookies.get("access_token")
    
    if not token:
        # Try to get from Authorization header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    
    if not token:
        return None
    
    payload = verify_token(token)
    if not payload:
        return None
    
    user_id = payload.get("sub")
    role = payload.get("role")
    
    if not user_id or not role:
        return None
    
    try:
        db = get_database()
        
        if role == "user":
            user_doc = await db.users.find_one({"_id": ObjectId(user_id)})
            if user_doc:
                # Keep original ObjectId values and rely on field alias `_id` -> `id`
                user = User(**user_doc)
                return user
        elif role == "vendor":
            user_doc = await db.vendor_users.find_one({"_id": ObjectId(user_id)})
            if user_doc:
                # Keep original ObjectId values and rely on field alias `_id` -> `id`
                user = VendorUser(**user_doc)
                return user
        
        return None
        
    except Exception as e:
        print(f"Error in get_current_user: {e}")
        return None


async def get_current_user_required(
    current_user: Union[User, VendorUser] = Depends(get_current_user)
) -> Union[User, VendorUser]:
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


async def get_current_user_optional(
    current_user: Union[User, VendorUser] = Depends(get_current_user)
) -> Optional[Union[User, VendorUser]]:
    return current_user









