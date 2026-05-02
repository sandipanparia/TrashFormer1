from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, UploadFile, File, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional, Union
import os
import uuid
from datetime import date, datetime

from ..database import get_database
from ..models import EWasteItem, Department, Category, User, VendorUser
from ..enums import ItemStatus, CategoryType, UserRole
from ..utils import generate_qr_png_bytes, get_current_user_optional

router = APIRouter(prefix="/items", tags=["items"])
templates = Jinja2Templates(directory="templates")





@router.get("/", response_class=HTMLResponse)
async def list_items(request: Request, q: Optional[str] = Query(None), current_user=Depends(get_current_user_optional)):
    db = get_database()
    
    # Build query based on search parameter
    query = {}
    if q:
        # Try to match by ObjectId first (exact match)
        try:
            from bson import ObjectId
            oid = ObjectId(q)
            query["_id"] = oid
        except:
            # If not a valid ObjectId, search by partial ID match
            query["_id"] = {"$regex": q, "$options": "i"}
    
    # Get items from MongoDB
    items_cursor = db.ewaste_items.find(query)
    items = await items_cursor.to_list(length=100)
    
    # Get departments and categories for display
    departments = await db.departments.find({}).to_list(length=100)
    categories = await db.categories.find({}).to_list(length=100)
    # Add string `id` for template selects
    for d in departments:
        try:
            d["id"] = str(d.get("_id"))
        except Exception:
            pass
    for c in categories:
        try:
            c["id"] = str(c.get("_id"))
        except Exception:
            pass
    
    # Convert ObjectIds to strings for display
    for item in items:
        item_str_id = str(item["_id"]) if "_id" in item else None
        item["_id"] = item_str_id
        item["id"] = item_str_id
        if "category_id" in item:
            item["category_id"] = str(item["category_id"])
        if "department_id" in item:
            item["department_id"] = str(item["department_id"])
        if "reported_by_id" in item:
            item["reported_by_id"] = str(item["reported_by_id"])
    
    return templates.TemplateResponse(
        "items.html",
        {
            "request": request,
            "items": items,
            "departments": departments,
            "categories": categories,
            "current_user": current_user,
            "search_query": q,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_item_form(request: Request, current_user=Depends(get_current_user_optional)):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=302)
    # Disallow vendors from adding items
    try:
        role_str = str(getattr(current_user, "role", "")).lower()
    except Exception:
        role_str = ""
    if role_str == "vendor":
        return RedirectResponse(url="/items/", status_code=302)
    
    db = get_database()
    departments = await db.departments.find({}).to_list(length=100)
    categories = await db.categories.find({}).to_list(length=100)
    # Normalize ids for template selects
    for d in departments:
        try:
            d["id"] = str(d["_id"])  # keep original _id too
        except Exception:
            pass
    for c in categories:
        try:
            c["id"] = str(c["_id"])  # keep original _id too
        except Exception:
            pass
    
    return templates.TemplateResponse(
        "add_item.html",
        {
            "request": request,
            "departments": departments,
            "categories": categories,
            "current_user": current_user,
        },
    )


@router.post("/new", response_class=HTMLResponse)
async def create_item(
    request: Request,
    name: str = Form(...),
    serial_number: Optional[str] = Form(None),
    category_id: str = Form(...),
    department_id: str = Form(...),
    purchase_date: Optional[str] = Form(None),
    weight_kg: Optional[str] = Form(None),
    price: Optional[str] = Form(None),
    disposition_type: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    current_user=Depends(get_current_user_optional)
):
    try:
        if not current_user:
            return RedirectResponse(url="/auth/login", status_code=302)
        # Disallow vendors from adding items
        try:
            role_str = str(getattr(current_user, "role", "")).lower()
        except Exception:
            role_str = ""
        if role_str == "vendor":
            return RedirectResponse(url="/items/", status_code=302)
        
        print(f"CREATE ITEM: User {current_user.id} creating item: {name}")
        
        db = get_database()
        
        # Validate disposition_type
        if not disposition_type or disposition_type not in ["selling", "disposed"]:
            print(f"CREATE ITEM ERROR: Invalid or missing disposition_type: {disposition_type}")
            raise HTTPException(status_code=400, detail="Please select whether you want to sell or dispose of this item")
        
        # Validate ObjectIds before conversion
        try:
            from bson import ObjectId
            category_oid = ObjectId(category_id)
            department_oid = ObjectId(department_id)
            print(f"CREATE ITEM: Valid ObjectIds - category: {category_oid}, department: {department_oid}")
        except Exception as e:
            print(f"CREATE ITEM ERROR: Invalid ObjectId - category_id: {category_id}, department_id: {department_id}")
            print(f"CREATE ITEM ERROR: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Invalid category or department ID: {str(e)}")
        
        # Handle photo upload
        photo_path = None
        if photo:
            try:
                import uuid
                filename = f"{uuid.uuid4()}.{photo.filename.split('.')[-1]}"
                disk_relative_path = f"uploads/{filename}"
                with open(f"static/{disk_relative_path}", "wb") as f:
                    f.write(await photo.read())
                # Store as absolute URL path so templates don't resolve relative to /items
                photo_path = f"/static/{disk_relative_path}"
                print(f"CREATE ITEM: Photo uploaded to {photo_path}")
            except Exception as e:
                print(f"CREATE ITEM ERROR: Photo upload failed - {str(e)}")
                photo_path = None
        
        # Parse purchase date
        parsed_purchase_date = None
        if purchase_date:
            try:
                from datetime import date
                parsed_purchase_date = date.fromisoformat(purchase_date)
                print(f"CREATE ITEM: Parsed purchase date: {parsed_purchase_date}")
            except ValueError as e:
                print(f"CREATE ITEM WARNING: Invalid purchase date format: {purchase_date}")
                pass
        
        # Parse weight as float if provided
        parsed_weight = None
        if weight_kg is not None and str(weight_kg).strip() != "":
            try:
                parsed_weight = float(weight_kg)
                print(f"CREATE ITEM: Parsed weight: {parsed_weight}")
            except ValueError as e:
                print(f"CREATE ITEM WARNING: Invalid weight format: {weight_kg}")
                parsed_weight = None
        
        # Parse price as float if provided (only for selling items)
        parsed_price = None
        if disposition_type == "selling":
            if not price or str(price).strip() == "":
                print(f"CREATE ITEM ERROR: Selling item requires a price")
                raise HTTPException(status_code=400, detail="Please enter a selling price for items you want to sell")
            
            try:
                parsed_price = float(price)
                if parsed_price <= 0:
                    print(f"CREATE ITEM ERROR: Price must be greater than 0: {price}")
                    raise HTTPException(status_code=400, detail="Selling price must be greater than 0")
                print(f"CREATE ITEM: Parsed price: {parsed_price}")
            except ValueError as e:
                print(f"CREATE ITEM ERROR: Invalid price format: {price}")
                raise HTTPException(status_code=400, detail="Please enter a valid selling price (numbers only)")
        elif disposition_type == "disposed":
            parsed_price = None
            print(f"CREATE ITEM: Item marked as disposed, no price needed")
        
        # Create item document (ensure proper types)
        from datetime import datetime
        
        item_data = {
            "name": name,
            "serial_number": serial_number,
            "category_id": category_oid,
            "department_id": department_oid,
            # Store dates as ISO strings for MongoDB compatibility
            "purchase_date": parsed_purchase_date.isoformat() if parsed_purchase_date else None,
            "weight_kg": parsed_weight,
            "price": parsed_price,
            "disposition_type": disposition_type,
            "notes": notes,
            "photo_path": photo_path,
            "reported_by_id": str(current_user.id) if current_user else None,
            "reported_date": datetime.utcnow(),
            "status": ItemStatus.REPORTED,
        }
        
        print(f"CREATE ITEM: Item data prepared: {item_data}")
        
        # Insert into MongoDB
        result = await db.ewaste_items.insert_one(item_data)
        print(f"CREATE ITEM: Item inserted successfully with ID: {result.inserted_id}")
        
        return RedirectResponse(url="/items/", status_code=302)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"CREATE ITEM CRITICAL ERROR: {str(e)}")
        print(f"CREATE ITEM CRITICAL ERROR: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/delete/{item_id}")
async def delete_item(item_id: str, current_user=Depends(get_current_user_optional)):
    """Delete an item"""
    print(f"DELETE ENDPOINT CALLED with item_id: {item_id}")
    
    if not current_user:
        print("No current user")
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    print(f"Current user: {current_user.id}, role: {current_user.role}")
    
    db = get_database()
    
    try:
        from bson import ObjectId
        oid = ObjectId(item_id)
    except Exception:
        print(f"Invalid ObjectId: {item_id}")
        raise HTTPException(status_code=400, detail="Invalid item id")
    
    # Get the item first to check ownership and get photo path
    item = await db.ewaste_items.find_one({"_id": oid})
    if not item:
        print(f"Item not found: {item_id}")
        raise HTTPException(status_code=404, detail="Item not found")
    
    print(f"Found item: {item}")
    
    # Check if user owns the item (only users can delete their own items)
    item_owner_id = item.get("reported_by_id")
    current_user_id = str(current_user.id)
    
    print(f"Item owner ID: {item_owner_id}, Current user ID: {current_user_id}")
    
    # Convert item_owner_id to string if it's an ObjectId
    if isinstance(item_owner_id, ObjectId):
        item_owner_id = str(item_owner_id)
        print(f"Converted ObjectId to string: {item_owner_id}")
    
    # If item doesn't have reported_by_id, set it to current user
    if not item_owner_id and current_user:
        print(f"Setting reported_by_id to current user: {current_user_id}")
        await db.ewaste_items.update_one(
            {"_id": oid},
            {"$set": {"reported_by_id": current_user_id}}
        )
        item_owner_id = current_user_id
    
    print(f"Final comparison: item_owner_id={item_owner_id}, current_user_id={current_user_id}")
    print(f"Are they equal? {item_owner_id == current_user_id}")
    
    # For vendors, also check if they have any pickup requests for this item
    if current_user.role == "VENDOR" and item_owner_id != current_user_id:
        print("User is vendor, checking pickup requests")
        # Check if vendor has an approved pickup request for this item
        pickup_request = await db.pickup_requests.find_one({
            "item_id": oid,
            "vendor_id": str(current_user.id),
            "status": "approved"
        })
        if pickup_request:
            print("Vendor has approved pickup request, allowing deletion")
            # Vendor can delete items they have approved pickup requests for
            pass
        else:
            print("Vendor has no approved pickup request")
            raise HTTPException(status_code=403, detail="You can only delete items you own or have approved pickup requests for")
    elif item_owner_id != current_user_id:
        print("User does not own this item")
        raise HTTPException(status_code=403, detail="You can only delete your own items")
    else:
        print("User owns this item, proceeding with deletion")
    
    # Delete the item
    print("Deleting item from database...")
    result = await db.ewaste_items.delete_one({"_id": oid})
    
    if result.deleted_count == 0:
        print("Failed to delete item from database")
        raise HTTPException(status_code=404, detail="Item not found")
    
    print("Item successfully deleted from database")
    
    # Delete associated photo if it exists
    if item.get("photo_path"):
        try:
            import os
            photo_path = item["photo_path"]
            if os.path.exists(photo_path):
                os.remove(photo_path)
                print(f"Photo file deleted: {photo_path}")
        except Exception as e:
            print(f"Warning: Could not delete photo file: {e}")
    
    # Delete associated pickup requests
    await db.pickup_requests.delete_many({"item_id": oid})
    print("Associated pickup requests deleted")
    
    return JSONResponse({
        "success": True,
        "message": "Item deleted successfully"
    })


@router.get("/{item_id}", response_class=HTMLResponse)
async def item_detail(request: Request, item_id: str, current_user=Depends(get_current_user_optional)):
    db = get_database()
    
    # Find item by ID
    from bson import ObjectId
    item = await db.ewaste_items.find_one({"_id": ObjectId(item_id)})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # Authorization: only owner (user) or approved vendor can view
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=302)
    from bson import ObjectId as _Oid
    owner_id_str = str(item.get("reported_by_id")) if item.get("reported_by_id") is not None else None
    current_user_id_str = str(getattr(current_user, "id", ""))
    role_val = getattr(current_user, "role", None)
    role_str = str(role_val).lower() if role_val is not None else ""
    is_vendor = (
        role_str == "vendor"
        or role_val == UserRole.VENDOR
        or (getattr(role_val, "value", "").lower() == "vendor")
    )
    if is_vendor:
        # Vendor must have an approved pickup request for this item
        approved = await db.pickup_requests.find_one({
            "item_id": _Oid(item_id),
            "$or": [
                {"vendor_id": current_user_id_str},
                {"vendor_id": _Oid(current_user_id_str)}
            ],
            "status": "approved"
        })
        if not approved:
            raise HTTPException(status_code=403, detail="You don't have permission to view this item")
        # Redirect vendors to the dedicated vendor details page
        return RedirectResponse(url=f"/pickup/item/{item_id}/details", status_code=302)
    else:
        # Regular user can only see their own item's details
        if owner_id_str != current_user_id_str:
            raise HTTPException(status_code=403, detail="You can only view your own items")

    # Get related data
    category = await db.categories.find_one({"_id": ObjectId(item["category_id"])})
    department = await db.departments.find_one({"_id": ObjectId(item["department_id"])})
    
    # Get status history logs
    logs = await db.item_status_logs.find({"item_id": ObjectId(item_id)}).sort("changed_at", -1).to_list(length=50)
    
    # Convert ObjectIds to strings
    item["_id"] = str(item["_id"])
    item["id"] = item["_id"]
    if "reported_by_id" in item:
        item["reported_by_id"] = str(item["reported_by_id"])
    if category:
        category["_id"] = str(category["_id"])
    if department:
        department["_id"] = str(department["_id"])
    
    # Build item URL for display/sharing (same logic as QR)
    import os, socket
    host_header = request.headers.get("host", "")
    scheme = request.url.scheme or "http"
    port = request.url.port
    public_base = os.environ.get("PUBLIC_BASE_URL")
    if public_base:
        base = public_base.rstrip("/")
    else:
        host_name = host_header.split(":")[0]
        needs_lan = (not host_name) or host_name in ("127.0.0.1", "localhost", "0.0.0.0")
        if needs_lan:
            try:
                tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    tmp.connect(("8.8.8.8", 80))
                    lan_ip = tmp.getsockname()[0]
                finally:
                    tmp.close()
            except Exception:
                try:
                    lan_ip = socket.gethostbyname(socket.gethostname())
                except Exception:
                    lan_ip = host_name or "127.0.0.1"
            if port:
                base = f"{scheme}://{lan_ip}:{port}"
            else:
                base = f"{scheme}://{lan_ip}"
        else:
            base = f"{scheme}://{host_header}"
    item_url = f"{base}/items/{item_id}"

    return templates.TemplateResponse(
        "item_detail.html",
        {
            "request": request,
            "item": item,
            "category": category,
            "department": department,
            "current_user": current_user,
            "statuses": list(ItemStatus),
            "item_url": item_url,
            "logs": logs,
        },
    )


@router.post("/{item_id}/status")
async def update_item_status(
    item_id: str, 
    status: str = Form(...),
    remarks: str = Form(""),
    current_user: Union[User, VendorUser] = Depends(get_current_user_optional)
):
    """Update item status - only vendors with approved pickup requests can update"""
    print(f"DEBUG: update_item_status called for item_id: {item_id}, status: {status}, remarks: {remarks}")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Only vendors can update status
    role_val = getattr(current_user, "role", None)
    role_str = str(role_val).lower() if role_val is not None else ""
    is_vendor = (
        role_str == "vendor"
        or role_val == UserRole.VENDOR
        or (getattr(role_val, "value", "").lower() == "vendor")
    )
    
    if not is_vendor:
        raise HTTPException(status_code=403, detail="Only vendors can update item status")
    
    # Validate status value
    valid_statuses = ["COLLECTED", "IN_STORAGE", "SENT_TO_VENDOR", "RECYCLED", "DISPOSED"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
    
    db = get_database()
    from bson import ObjectId
    
    try:
        oid = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid item id")
    
    # Check if vendor has an approved pickup request for this item
    vendor_id_or_clauses = [{"vendor_id": str(current_user.id)}]
    try:
        vendor_oid = ObjectId(str(current_user.id))
        vendor_id_or_clauses.append({"vendor_id": vendor_oid})
    except Exception:
        pass
    
    approved_request = await db.pickup_requests.find_one({
        "item_id": oid,
        "$or": vendor_id_or_clauses,
        "status": {"$in": ["approved", "completed"]}
    })
    
    if not approved_request:
        raise HTTPException(status_code=403, detail="You don't have an approved pickup request for this item")
    
    # Get current item status from the item itself for logging
    item_doc = await db.ewaste_items.find_one({"_id": oid})
    if not item_doc:
        raise HTTPException(status_code=404, detail="Item not found")
    current_item_status = item_doc.get("status", "unknown")
    
    print(f"DEBUG: Current item status: {current_item_status}, updating to: {status}")
    
    # Update the item's status in the ewaste_items collection
    # Use $set to only update the status field, preserving all other fields
    item_update_result = await db.ewaste_items.update_one(
        {"_id": oid},
        {"$set": {"status": status}}
    )
    
    print(f"DEBUG: Item update result - matched: {item_update_result.matched_count}, modified: {item_update_result.modified_count}")
    
    if item_update_result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Item not found during update")
    
    if item_update_result.modified_count == 0:
        print(f"DEBUG: Status unchanged - item already has status: {status}")
        # Don't throw error if status is unchanged, just continue
    
    # Update pickup request with remarks and status if relevant
    pickup_update_data = {}
    if remarks:
        pickup_update_data["vendor_notes"] = remarks
    
    # If status is COLLECTED, mark pickup request as completed
    if status == "COLLECTED":
        pickup_update_data["status"] = "completed"
    
    # Update pickup request if there are changes
    if pickup_update_data:
        await db.pickup_requests.update_one(
            {"_id": approved_request["_id"]},
            {"$set": pickup_update_data}
        )
    
    # Log the status change
    status_log = {
        "item_id": oid,
        "from_status": current_item_status,
        "to_status": status,
        "changed_by": str(current_user.id),
        "changed_at": datetime.utcnow(),
        "remarks": remarks,
        "user_type": "vendor"
    }
    
    await db.item_status_logs.insert_one(status_log)
    
    return {"message": "Status updated successfully", "new_status": status}


@router.get("/qr/{item_id}", response_class=HTMLResponse)
async def public_qr_item_details(item_id: str, request: Request):
    """Public QR endpoint - shows item details without authentication for QR scanning"""
    db = get_database()
    
    try:
        from bson import ObjectId
        # Try to create ObjectId from the item_id
        oid = ObjectId(item_id)
        # Get item details using full ObjectId
        item = await db.ewaste_items.find_one({"_id": oid})
    except Exception:
        # If ObjectId creation fails, try to find item by truncated ID
        try:
            # Get all items and find one that starts with the given prefix
            all_items = await db.ewaste_items.find({}).to_list(length=1000)
            item = None
            for potential_item in all_items:
                if str(potential_item["_id"]).startswith(item_id):
                    item = potential_item
                    oid = potential_item["_id"]
                    break
            
            if not item:
                raise HTTPException(status_code=404, detail="Item not found")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid item id")
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # Get related data
    category = None
    department = None
    try:
        if item.get("category_id"):
            category = await db.categories.find_one({"_id": ObjectId(item["category_id"])})
        if item.get("department_id"):
            department = await db.departments.find_one({"_id": ObjectId(item["department_id"])})
    except Exception:
        pass
    
    # Convert ObjectIds to strings
    item["_id"] = str(item["_id"])
    item["id"] = item["_id"]
    
    # Get pickup request info if any
    pickup_request = None
    try:
        pickup_request = await db.pickup_requests.find_one({
            "item_id": oid,
            "status": {"$in": ["approved", "completed"]}
        })
    except Exception:
        pass
    
    if category:
        category["_id"] = str(category["_id"])
    if department:
        department["_id"] = str(department["_id"])
    
    return templates.TemplateResponse(
        "qr_item_details.html",
        {
            "request": request,
            "item": item,
            "category": category,
            "department": department,
            "pickup_request": pickup_request,
        },
    )


@router.get("/{item_id}/qr.png")
async def item_qr_png(item_id: str, request: Request, current_user=Depends(get_current_user_optional)):
    db = get_database()
    from bson import ObjectId
    try:
        # Try to create ObjectId from the item_id
        oid = ObjectId(item_id)
        # Get item details using full ObjectId
        item = await db.ewaste_items.find_one({"_id": oid})
    except Exception:
        # If ObjectId creation fails, try to find item by truncated ID
        try:
            # Get all items and find one that starts with the given prefix
            all_items = await db.ewaste_items.find({}).to_list(length=1000)
            item = None
            for potential_item in all_items:
                if str(potential_item["_id"]).startswith(item_id):
                    item = potential_item
                    oid = potential_item["_id"]
                    break
            
            if not item:
                raise HTTPException(status_code=404, detail="Item not found")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid item id")
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    # Authorization: only owner or approved vendor can fetch QR
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    owner_id_str = str(item.get("reported_by_id")) if item.get("reported_by_id") is not None else None
    current_user_id_str = str(getattr(current_user, "id", ""))
    role_val = getattr(current_user, "role", None)
    role_str = str(role_val).lower() if role_val is not None else ""
    is_vendor = (
        role_str == "vendor"
        or role_val == UserRole.VENDOR
        or (getattr(role_val, "value", "").lower() == "vendor")
    )
    if owner_id_str != current_user_id_str:
        if is_vendor:
            # Build flexible vendor id matchers (string and ObjectId when possible)
            vendor_id_or_clauses = [{"vendor_id": current_user_id_str}]
            try:
                vendor_oid = ObjectId(current_user_id_str)
                vendor_id_or_clauses.append({"vendor_id": vendor_oid})
            except Exception:
                pass
            approved = await db.pickup_requests.find_one({
                "item_id": oid,
                "$or": vendor_id_or_clauses,
                "status": "approved"
            })
            if not approved:
                raise HTTPException(status_code=403, detail="You don't have permission to view this QR")
        else:
            raise HTTPException(status_code=403, detail="You don't have permission to view this QR")
    
    # Build a URL to the public QR endpoint
    import os, socket
    host_header = request.headers.get("host", "")
    scheme = request.url.scheme or "http"
    port = request.url.port
    public_base = os.environ.get("PUBLIC_BASE_URL")
    if public_base:
        base = public_base.rstrip("/")
    else:
        # If accessed via 127.0.0.1/localhost on desktop, replace with LAN IP for mobile scanning
        host_name = host_header.split(":")[0]
        needs_lan = (not host_name) or host_name in ("127.0.0.1", "localhost", "0.0.0.0")
        if needs_lan:
            # Try to detect active LAN IP via a UDP socket trick (no packets sent)
            try:
                tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    tmp.connect(("8.8.8.8", 80))
                    lan_ip = tmp.getsockname()[0]
                finally:
                    tmp.close()
            except Exception:
                try:
                    lan_ip = socket.gethostbyname(socket.gethostname())
                except Exception:
                    lan_ip = host_name or "127.0.0.1"
            if port:
                base = f"{scheme}://{lan_ip}:{port}"
            else:
                base = f"{scheme}://{lan_ip}"
        else:
            base = f"{scheme}://{host_header}"
    item_url = f"{base}/items/qr/{item_id}"
    qr_content = item_url
    qr_bytes = generate_qr_png_bytes(qr_content)
    
    from fastapi.responses import Response
    return Response(content=qr_bytes, media_type="image/png")

# Backward compatible QR endpoint without extension
@router.get("/{item_id}/qr")
async def item_qr(item_id: str, request: Request):
    return await item_qr_png(item_id, request)


@router.get("/{item_id}/download.pdf")
async def download_item_pdf(
    item_id: str,
    request: Request,
    vendor: Optional[str] = Query(None),
    current_user=Depends(get_current_user_optional),
):
    """Generate and download a PDF with item details.

    Authorization:
    - Owner (reporting user) can download
    - Vendor with approved or completed pickup request can download
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from bson import ObjectId
    db = get_database()

    try:
        oid = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid item id")

    item = await db.ewaste_items.find_one({"_id": oid})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Authorization check
    owner_id_str = str(item.get("reported_by_id")) if item.get("reported_by_id") is not None else None
    current_user_id_str = str(getattr(current_user, "id", ""))
    role_val = getattr(current_user, "role", None)
    role_str = str(role_val).lower() if role_val is not None else ""
    is_vendor = (
        role_str == "vendor"
        or role_val == UserRole.VENDOR
        or (getattr(role_val, "value", "").lower() == "vendor")
    )

    authorized = False
    if owner_id_str == current_user_id_str:
        authorized = True
    elif is_vendor:
        # Accept vendor id as string or ObjectId
        vendor_or_clauses = [{"vendor_id": current_user_id_str}]
        try:
            vendor_oid = ObjectId(current_user_id_str)
            vendor_or_clauses.append({"vendor_id": vendor_oid})
        except Exception:
            pass
        approved_request = await db.pickup_requests.find_one({
            "item_id": oid,
            "$or": vendor_or_clauses,
            "status": {"$in": ["approved", "completed"]}
        })
        authorized = approved_request is not None

    if not authorized:
        raise HTTPException(status_code=403, detail="You don't have permission to download this item details")

    # Fetch related names safely
    category_name = "-"
    department_name = "-"
    try:
        if item.get("category_id"):
            cat_doc = await db.categories.find_one({"_id": ObjectId(item["category_id"])})
            if cat_doc:
                category_name = cat_doc.get("name", "-")
        if item.get("department_id"):
            dep_doc = await db.departments.find_one({"_id": ObjectId(item["department_id"])})
            if dep_doc:
                department_name = dep_doc.get("name", "-")
    except Exception:
        pass

    # Build item URL for QR (same as QR endpoint)
    import os, socket, io
    host_header = request.headers.get("host", "")
    scheme = request.url.scheme or "http"
    port = request.url.port
    public_base = os.environ.get("PUBLIC_BASE_URL")
    if public_base:
        base = public_base.rstrip("/")
    else:
        host_name = host_header.split(":")[0]
        needs_lan = (not host_name) or host_name in ("127.0.0.1", "localhost", "0.0.0.0")
        if needs_lan:
            try:
                tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    tmp.connect(("8.8.8.8", 80))
                    lan_ip = tmp.getsockname()[0]
                finally:
                    tmp.close()
            except Exception:
                try:
                    lan_ip = socket.gethostbyname(socket.gethostname())
                except Exception:
                    lan_ip = host_name or "127.0.0.1"
            if port:
                base = f"{scheme}://{lan_ip}:{port}"
            else:
                base = f"{scheme}://{lan_ip}"
        else:
            base = f"{scheme}://{host_header}"
    
    # Use public endpoint for QR code so mobile scanning works
    item_url = f"{base}/items/qr/{item_id}"

    # Prepare PDF
    try:
        from reportlab.pdfgen import canvas as rl_canvas
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.utils import ImageReader
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation library not available: {str(e)}")

    buffer = io.BytesIO()
    pdf = rl_canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Header
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, height - 50, "E-Waste Item Details")

    # QR code on top-right
    try:
        print(f"PDF DEBUG: Generating QR for URL: {item_url}")
        qr_bytes = generate_qr_png_bytes(item_url)
        qr_img = ImageReader(io.BytesIO(qr_bytes))
        qr_size = 120
        pdf.drawImage(qr_img, width - qr_size - 40, height - qr_size - 40, qr_size, qr_size, preserveAspectRatio=True, mask='auto')
        print(f"PDF DEBUG: QR code added successfully")
    except Exception as e:
        print(f"PDF DEBUG: Error adding QR code: {e}")
        pass

    # Details block
    pdf.setFont("Helvetica", 11)
    y = height - 90
    line_gap = 16

    def draw_kv(label: str, value: str):
        nonlocal y
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(40, y, f"{label}:")
        pdf.setFont("Helvetica", 11)
        pdf.drawString(180, y, value or "-")
        y -= line_gap

    draw_kv("Item Name", str(item.get("name", "-")))
    draw_kv("Item ID", str(item.get("_id", "-")))
    draw_kv("Status", str(item.get("status", "-")).replace("_", " ").title())
    draw_kv("Category", category_name)
    draw_kv("Department", department_name)
    draw_kv("Serial Number", str(item.get("serial_number", "-")))
    draw_kv("Purchase Date", str(item.get("purchase_date", "-")))
    draw_kv("Reported Date", str(item.get("reported_date", "-")))
    draw_kv("Weight (kg)", str(item.get("weight_kg", "-")))
    draw_kv("Price", f"${item.get('price', '-')}" if item.get('price') else "-")

    # Notes (multi-line)
    notes = str(item.get("notes", ""))
    if notes:
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(40, y, "Notes:")
        y -= line_gap
        pdf.setFont("Helvetica", 11)
        # Simple wrap
        max_chars = 90
        for i in range(0, len(notes), max_chars):
            pdf.drawString(40, y, notes[i:i+max_chars])
            y -= line_gap

    # Footer
    pdf.setFont("Helvetica-Oblique", 9)
    footer_text = f"Generated on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    pdf.drawRightString(width - 40, 30, footer_text)

    pdf.showPage()
    pdf.save()
    buffer.seek(0)

    from fastapi.responses import Response
    filename = f"item_{item_id}.pdf"
    headers = {"Content-Disposition": f"attachment; filename=\"{filename}\""}
    return Response(content=buffer.read(), media_type="application/pdf", headers=headers)


# Simple test endpoint to verify mobile connectivity
@router.get("/test/mobile-connect", response_class=HTMLResponse)
async def mobile_connect_test(request: Request):
    """Ultra-simple test page to verify mobile can connect"""
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mobile Connection Test</title>
    <style>
        body {{ 
            font-family: Arial, sans-serif; 
            margin: 0; 
            padding: 20px; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-align: center;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }}
        .success-box {{ 
            background: rgba(255,255,255,0.1); 
            padding: 30px; 
            border-radius: 20px; 
            margin: 20px auto;
            max-width: 400px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.2);
        }}
        h1 {{ font-size: 3em; margin: 0 0 20px 0; }}
        .info {{ 
            background: rgba(0,0,0,0.2); 
            padding: 15px; 
            border-radius: 10px; 
            margin: 15px 0;
            font-size: 14px;
        }}
        .big-text {{ font-size: 1.5em; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="success-box">
        <h1>🎉</h1>
        <div class="big-text">SUCCESS!</div>
        <div class="big-text">Your mobile phone can connect to the server!</div>
        
        <div class="info">
            <strong>Your Mobile IP:</strong><br>
            {request.client.host if request.client else 'Unknown'}
        </div>
        
        <div class="info">
            <strong>Server IP:</strong><br>
            10.24.226.72:8000
        </div>
        
        <div class="info">
            <strong>Time:</strong><br>
            <span id="time"></span>
        </div>
        
        <div class="big-text" style="margin-top: 30px;">
            ✅ QR Code Scanning Will Work!
        </div>
    </div>
    
    <script>
        document.getElementById('time').textContent = new Date().toLocaleString();
    </script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ULTRA-SIMPLE item details for mobile - NO external dependencies
@router.get("/simple-mobile/{item_id}", response_class=HTMLResponse)
async def ultra_simple_item_details(item_id: str, request: Request):
    """Ultra-simple item details that will definitely work on mobile"""
    db = get_database()
    
    try:
        from bson import ObjectId
        oid = ObjectId(item_id)
    except Exception:
        return HTMLResponse(content="<h1>❌ Invalid Item ID</h1>")
    
    # Get item details
    item = await db.ewaste_items.find_one({"_id": oid})
    if not item:
        return HTMLResponse(content="<h1>❌ Item Not Found</h1>")
    
    # Get category and department names
    category_name = "N/A"
    department_name = "N/A"
    
    try:
        if item.get("category_id"):
            category = await db.categories.find_one({"_id": ObjectId(item["category_id"])})
            if category:
                category_name = category.get("name", "N/A")
        
        if item.get("department_id"):
            department = await db.departments.find_one({"_id": ObjectId(item["department_id"])})
            if department:
                department_name = department.get("name", "N/A")
    except Exception:
        pass
    
    # Create ultra-simple HTML with NO external dependencies
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Item Details</title>
    <style>
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0; 
            padding: 20px; 
            background: #f0f2f5;
            color: #1a1a1a;
        }}
        .container {{ 
            max-width: 500px; 
            margin: 0 auto; 
            background: white; 
            border-radius: 16px; 
            padding: 24px; 
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        }}
        .header {{ 
            text-align: center; 
            margin-bottom: 24px; 
            padding-bottom: 16px; 
            border-bottom: 2px solid #e1e5e9;
        }}
        .header h1 {{ 
            margin: 0; 
            color: #1a73e8; 
            font-size: 28px;
        }}
        .info-row {{ 
            display: flex; 
            justify-content: space-between; 
            padding: 12px 0; 
            border-bottom: 1px solid #f0f0f0;
        }}
        .label {{ 
            font-weight: 600; 
            color: #5f6368; 
            min-width: 120px;
        }}
        .value {{ 
            color: #202124; 
            text-align: right;
            flex: 1;
        }}
        .status {{ 
            background: #e8f5e8; 
            color: #0f5132; 
            padding: 4px 12px; 
            border-radius: 20px; 
            font-size: 12px; 
            font-weight: 600;
        }}
        .footer {{ 
            text-align: center; 
            margin-top: 24px; 
            padding-top: 16px; 
            border-top: 1px solid #e1e5e9; 
            color: #5f6368; 
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📦 Item Details</h1>
        </div>
        
        <div class="info-row">
            <span class="label">📝 Name:</span>
            <span class="value">{item.get('name', 'N/A')}</span>
        </div>
        
        <div class="info-row">
            <span class="label">🆔 ID:</span>
            <span class="value">#{str(item.get('_id', ''))[:8]}</span>
        </div>
        
        <div class="info-row">
            <span class="label">📊 Status:</span>
            <span class="value"><span class="status">{item.get('status', 'N/A').replace('_', ' ').title()}</span></span>
        </div>
        
        <div class="info-row">
            <span class="label">🏷️ Category:</span>
            <span class="value">{category_name}</span>
        </div>
        
        <div class="info-row">
            <span class="label">🏢 Department:</span>
            <span class="value">{department_name}</span>
        </div>
        
        {f'<div class="info-row"><span class="label">📊 Serial:</span><span class="value">{item.get("serial_number")}</span></div>' if item.get("serial_number") else ''}
        
        {f'<div class="info-row"><span class="label">⚖️ Weight:</span><span class="value">{item.get("weight_kg")} kg</span></div>' if item.get("weight_kg") else ''}
        
        {f'<div class="info-row"><span class="label">💰 Price:</span><span class="value">${item.get("price")}</span></div>' if item.get("price") else ''}
        
        {f'<div class="info-row"><span class="label">📝 Notes:</span><span class="value">{item.get("notes")}</span></div>' if item.get("notes") else ''}
        
        <div class="info-row">
            <span class="label">✅ Reported:</span>
            <span class="value">{item.get('reported_date', 'N/A')}</span>
        </div>
        
        <div class="footer">
            📱 Scanned via QR Code • {request.client.host if request.client else 'Unknown'}
        </div>
    </div>
</body>
</html>"""
    
    return HTMLResponse(content=html)






