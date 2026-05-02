from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from datetime import timedelta
from bson import ObjectId

from ..database import get_database
from ..models import User, VendorUser, Department, Vendor, get_password_hash, verify_password
from ..enums import UserRole
from ..utils import create_access_token, get_current_user_optional

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("auth/login.html", {"request": request})


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    user_type: str = Form(...)
):
    db = get_database()
    
    # Find user based on type
    if user_type == "user":
        user_doc = await db.users.find_one({"username": username})
        user_class = User
    elif user_type == "vendor":
        user_doc = await db.vendor_users.find_one({"username": username})
        user_class = VendorUser
    else:
        return templates.TemplateResponse(
            "auth/login.html", 
            {"request": request, "error": "Invalid user type"}
        )
    
    if not user_doc or not verify_password(password, user_doc["hashed_password"]):
        return templates.TemplateResponse(
            "auth/login.html", 
            {"request": request, "error": "Invalid username or password"}
        )
    
    # Create access token
    access_token = create_access_token(
        data={"sub": str(user_doc["_id"]), "role": user_type}
    )
    
    # Create response with redirect to profile
    response = RedirectResponse(url="/auth/profile", status_code=302)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    
    return response


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    db = get_database()
    departments = await db.departments.find({}).to_list(length=100)
    vendors = await db.vendors.find({}).to_list(length=100)
    
    return templates.TemplateResponse(
        "auth/signup.html", 
        {
            "request": request, 
            "departments": departments,
            "vendors": vendors
        }
    )


@router.post("/signup", response_class=HTMLResponse)
async def signup(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    phone: Optional[str] = Form(None),
    user_type: str = Form(...),
    department_id: Optional[str] = Form(None),
    vendor_id: Optional[str] = Form(None)
):
    db = get_database()
    
    # Check if username already exists
    existing_user = await db.users.find_one({"username": username})
    existing_vendor = await db.vendor_users.find_one({"username": username})
    
    if existing_user or existing_vendor:
        return templates.TemplateResponse(
            "auth/signup.html", 
            {"request": request, "error": "Username already exists"}
        )
    
    # Check if email already exists
    existing_user = await db.users.find_one({"email": email})
    existing_vendor = await db.vendor_users.find_one({"email": email})
    
    if existing_user or existing_vendor:
        return templates.TemplateResponse(
            "auth/signup.html", 
            {"request": request, "error": "Email already exists"}
        )
    
    # Hash password
    hashed_password = get_password_hash(password)
    
    # Create user document
    user_data = {
        "username": username,
        "email": email,
        "full_name": full_name,
        "phone": phone,
        "hashed_password": hashed_password,
        "is_active": True
    }
    
    if user_type == "user":
        if department_id:
            user_data["department_id"] = department_id
        user_data["role"] = UserRole.USER
        result = await db.users.insert_one(user_data)
    elif user_type == "vendor":
        if vendor_id:
            user_data["vendor_id"] = vendor_id
        user_data["role"] = UserRole.VENDOR
        result = await db.vendor_users.insert_one(user_data)
    else:
        return templates.TemplateResponse(
            "auth/signup.html", 
            {"request": request, "error": "Invalid user type"}
        )
    
    # Create access token
    access_token = create_access_token(
        data={"sub": str(result.inserted_id), "role": user_type}
    )
    
    # Create response with redirect to profile
    response = RedirectResponse(url="/auth/profile", status_code=302)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    
    return response


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, current_user=Depends(get_current_user_optional)):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    db = get_database()
    role = "user"
    extra = {}
    try:
        # Determine role based on user type and attributes
        if current_user.__class__.__name__ == 'VendorUser':
            role = "vendor"
        elif hasattr(current_user, "vendor_id") and current_user.vendor_id:
            role = "vendor"
        elif hasattr(current_user, "role") and current_user.role == UserRole.VENDOR:
            role = "vendor"
        else:
            role = "user"
        
        # Attempt to enrich with related info for display
        if hasattr(current_user, "department_id") and current_user.department_id:
            try:
                from bson import ObjectId
                dept = await db.departments.find_one({"_id": ObjectId(str(current_user.department_id))})
                if dept:
                    extra["department_name"] = dept.get("name")
            except Exception:
                pass
        if hasattr(current_user, "vendor_id") and current_user.vendor_id:
            try:
                from bson import ObjectId
                ven = await db.vendors.find_one({"_id": ObjectId(str(current_user.vendor_id))})
                if ven:
                    extra["vendor_name"] = ven.get("name")
                    extra["vendor_verified"] = bool(ven.get("is_verified"))
                    extra["vendor_license_no"] = ven.get("license_no")
            except Exception:
                pass
    except Exception as e:
        pass
    
    # Compute user's reported item stats
    try:
        from bson import ObjectId
        uid_str = str(getattr(current_user, "id", ""))
        filt = {"$or": [{"reported_by_id": uid_str}]}
        # Support ObjectId storage as well
        try:
            filt["$or"].append({"reported_by_id": ObjectId(uid_str)})
        except Exception:
            pass
        user_items = await db.ewaste_items.find(filt).to_list(length=1000)
        total_items = len(user_items)
        in_progress_statuses = {"REPORTED", "COLLECTED", "IN_STORAGE", "SENT_TO_VENDOR"}
        status_of = lambda it: (it.get("status").value if hasattr(it.get("status"), "value") else str(it.get("status")))
        in_progress = sum(1 for it in user_items if status_of(it) in in_progress_statuses)
        recycled = sum(1 for it in user_items if status_of(it) == "RECYCLED")
        disposed = sum(1 for it in user_items if status_of(it) == "DISPOSED")
        extra.update({
            "total_reported_items": total_items,
            "total_in_progress": in_progress,
            "total_recycled": recycled,
            "total_disposed": disposed,
        })
    except Exception as e:
        extra.update({
            "total_reported_items": 0,
            "total_in_progress": 0,
            "total_recycled": 0,
            "total_disposed": 0,
        })
    
    return templates.TemplateResponse(
        "auth/profile.html",
        {"request": request, "user": current_user, "role": role, **extra}
    )


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(key="access_token")
    return response


@router.get("/dashboard/user_dashboard", response_class=HTMLResponse)
async def user_dashboard(request: Request, current_user=Depends(get_current_user_optional)):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    if current_user.role != UserRole.USER:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    db = get_database()
    
    try:
        # Get user's reported items (support both string and ObjectId in DB)
        from bson import ObjectId
        user_id_str = str(current_user.id)
        filt = {"$or": [{"reported_by_id": user_id_str}]}
        try:
            filt["$or"].append({"reported_by_id": ObjectId(user_id_str)})
        except Exception:
            pass
        user_items = await db.ewaste_items.find(filt).to_list(length=1000)
        
        # Count items by status
        total_items = len(user_items)
        in_progress_statuses = {"REPORTED", "COLLECTED", "IN_STORAGE", "SENT_TO_VENDOR"}
        def status_of(it):
            st = it.get("status")
            return st.value if hasattr(st, "value") else str(st)
        in_progress = sum(1 for it in user_items if status_of(it) in in_progress_statuses)
        recycled = sum(1 for it in user_items if status_of(it) == "RECYCLED")
        disposed = sum(1 for it in user_items if status_of(it) == "DISPOSED")
        
        return templates.TemplateResponse(
            "dashboard/user_dashboard.html",
            {
                "request": request,
                "current_user": current_user,
                "user": current_user,
                "total_items": total_items,
                "in_progress": in_progress,
                "recycled": recycled,
                "disposed": disposed
            }
        )
    except Exception as e:
        print(f"Error in user dashboard: {e}")
        # Return dashboard with default values if there's an error
        return templates.TemplateResponse(
            "dashboard/user_dashboard.html",
            {
                "request": request,
                "current_user": current_user,
                "user": current_user,
                "total_items": 0,
                "in_progress": 0,
                "recycled": 0,
                "disposed": 0
            }
        )


@router.get("/dashboard/vendor_dashboard", response_class=HTMLResponse)
async def vendor_dashboard(request: Request, current_user=Depends(get_current_user_optional)):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    # Check if user is a vendor by multiple criteria
    is_vendor = False
    
    # Check by class type
    if current_user.__class__.__name__ == 'VendorUser':
        is_vendor = True
    
    # Check by role
    elif hasattr(current_user, 'role') and current_user.role == UserRole.VENDOR:
        is_vendor = True
    
    # Check by vendor_id
    elif hasattr(current_user, 'vendor_id') and current_user.vendor_id:
        is_vendor = True
    
    if not is_vendor:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    db = get_database()
    
    try:
        # Get vendor info
        vendor = None
        if current_user.vendor_id:
            try:
                # Convert vendor_id to ObjectId if it's a string
                vendor_id = current_user.vendor_id if isinstance(current_user.vendor_id, ObjectId) else ObjectId(current_user.vendor_id)
                vendor = await db.vendors.find_one({"_id": vendor_id})
            except Exception as e:
                print(f"Error getting vendor info: {e}")
                vendor = None
        
        # Get vendor's schedules
        vendor_schedules = []
        if current_user.vendor_id:
            try:
                vendor_id_str = str(current_user.vendor_id)
                vendor_schedules = await db.schedules.find({"vendor_id": vendor_id_str}).to_list(length=100)
            except Exception as e:
                print(f"Error getting vendor schedules: {e}")
        
        # Get vendor statistics for dashboard display
        try:
            vendor_id_str = str(current_user.vendor_id) if current_user.vendor_id else str(current_user.id)
            
            # Get all e-waste items that are available for collection
            reported_count = await db.ewaste_items.count_documents({"status": "REPORTED"})
            collected_count = await db.ewaste_items.count_documents({"status": "COLLECTED"})
            in_storage_count = await db.ewaste_items.count_documents({"status": "IN_STORAGE"})
            
            # Calculate total available items
            total_available_items = reported_count + collected_count + in_storage_count
            
            # Get vendor's own pickup requests for statistics
            vendor_pickup_requests = await db.pickup_requests.find({
                "vendor_id": vendor_id_str
            }).to_list(length=None)
            
            # Get vendor's pickup request status breakdown
            pickup_status_counts = {}
            for status in ["pending", "approved", "rejected", "completed"]:
                count = len([req for req in vendor_pickup_requests if req.get("status") == status])
                pickup_status_counts[status] = count
            
            # Set the statistics for dashboard display
            total_items = total_available_items
            pickup_requests_count = reported_count  # Show reported items count
            completed_requests_count = len(vendor_pickup_requests)  # Show vendor's total requests
            disposed_count = collected_count + in_storage_count  # Show collected + storage items
            approved_count = pickup_status_counts.get("approved", 0)
            
        except Exception as e:
            print(f"Error getting vendor statistics: {e}")
            # Set default values if there's an error
            total_items = 0
            pickup_requests_count = 0
            completed_requests_count = 0
            disposed_count = 0
            approved_count = 0
        
        # Debug: Print the statistics being sent (available items + vendor requests)
        print(f"Vendor Dashboard Stats (Available Items) - Total Items: {total_items}, Pending: {pickup_requests_count}, Completed: {completed_requests_count}, Collected/Storage: {disposed_count}, Approved: {approved_count}")
        
        return templates.TemplateResponse(
            "dashboard/vendor_dashboard.html",
            {
                "request": request,
                "current_user": current_user,
                "user": current_user,
                "vendor": vendor,
                "vendor_items": [],
                "available_items": [],
                "schedules_count": len(vendor_schedules),
                "items_count": total_items,
                "pickup_requests_count": pickup_requests_count,
                "completed_requests_count": completed_requests_count,
                "disposed_count": disposed_count,
                "approved_count": approved_count
            }
        )
    except Exception as e:
        print(f"Error in vendor dashboard: {e}")
        # Return dashboard with default values if there's an error
        return templates.TemplateResponse(
            "dashboard/vendor_dashboard.html",
            {
                "request": request,
                "current_user": current_user,
                "user": current_user,
                "vendor": None,
                "vendor_items": [],
                "available_items": [],
                "schedules_count": 0,
                "items_count": 0,
                "pickup_requests_count": 0,
                "completed_requests_count": 0,
                "disposed_count": 0,
                "approved_count": 0
            }
        )


