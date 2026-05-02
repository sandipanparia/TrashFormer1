from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from bson import ObjectId
from enum import Enum

from .enums import ItemStatus, CategoryType, UserRole


class PyObjectId(ObjectId):
    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        # Allow Pydantic v2 to treat bson.ObjectId as a string type for JSON
        from pydantic_core import core_schema
        return core_schema.json_or_python_schema(
            json_schema=core_schema.str_schema(),
            python_schema=core_schema.is_instance_schema(ObjectId),
            serialization=core_schema.plain_serializer_function_ser_schema(lambda v: str(v)),
        )


class User(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    username: str = Field(unique=True, index=True)
    email: str = Field(unique=True, index=True)
    full_name: str
    phone: Optional[str] = None
    department_id: Optional[PyObjectId] = None
    role: UserRole = UserRole.USER
    is_active: bool = True
    hashed_password: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        validate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class VendorUser(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    username: str = Field(unique=True, index=True)
    email: str = Field(unique=True, index=True)
    full_name: str
    phone: Optional[str] = None
    vendor_id: Optional[PyObjectId] = None
    role: UserRole = UserRole.VENDOR
    is_active: bool = True
    hashed_password: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        validate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class Department(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    name: str = Field(unique=True, index=True)
    description: Optional[str] = None
    
    class Config:
        validate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class Category(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    name: str = Field(unique=True, index=True)
    type: CategoryType
    description: Optional[str] = None
    
    class Config:
        validate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class Vendor(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    name: str = Field(unique=True, index=True)
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    license_no: Optional[str] = None
    address: Optional[str] = None
    is_verified: bool = False
    
    class Config:
        validate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class EWasteItem(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    name: str
    serial_number: Optional[str] = Field(unique=True, index=True)
    category_id: PyObjectId
    department_id: PyObjectId
    purchase_date: Optional[date] = None
    reported_date: datetime = Field(default_factory=datetime.utcnow)
    status: ItemStatus = ItemStatus.REPORTED
    weight_kg: Optional[float] = None
    price: Optional[float] = Field(None, description="Item price in currency")
    disposition_type: Optional[str] = Field(None, description="Item disposition: selling or disposed")
    notes: Optional[str] = None
    photo_path: Optional[str] = None
    reported_by_id: Optional[PyObjectId] = None
    
    class Config:
        validate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class ItemStatusLog(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    item_id: PyObjectId
    from_status: Optional[ItemStatus] = None
    to_status: ItemStatus
    remarks: Optional[str] = None
    changed_at: datetime = Field(default_factory=datetime.utcnow)
    changed_by_id: Optional[PyObjectId] = None
    
    class Config:
        validate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class Schedule(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    scheduled_date: date
    vendor_id: PyObjectId
    department_id: Optional[PyObjectId] = None
    notes: Optional[str] = None
    status: str = "scheduled"  # scheduled, completed, cancelled
    
    class Config:
        validate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class ScheduleItem(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    schedule_id: PyObjectId
    item_id: PyObjectId
    
    class Config:
        validate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class Campaign(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    title: str
    description: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    points_awarded: int = 0
    is_active: bool = True
    
    class Config:
        validate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class PickupRequest(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    item_id: PyObjectId
    vendor_id: PyObjectId
    user_id: PyObjectId  # The user who reported the item
    status: str = "pending"  # pending, approved, rejected, completed
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    vendor_notes: Optional[str] = None
    user_notes: Optional[str] = None
    pickup_location: Optional[str] = None  # For storing location coordinates or address
    
    class Config:
        validate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


# Password hashing utilities
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

