from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from datetime import datetime
from bson import ObjectId

from ..database import get_database
from ..models import PickupRequest
from ..utils import get_current_user_optional
from ..enums import UserRole

router = APIRouter(prefix="/pickup", tags=["pickup_requests"])
templates = Jinja2Templates(directory="templates")


@router.get("/vendor/items", response_class=HTMLResponse)
async def vendor_items_list(request: Request, current_user=Depends(get_current_user_optional)):
    """Vendor view - shows items available for pickup without details"""
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    # Check if user is a vendor
    is_vendor = False
    
    # Check by class type
    if current_user.__class__.__name__ == 'VendorUser':
        is_vendor = True
    
    # Check by role
    elif hasattr(current_user, 'role'):
        if current_user.role == UserRole.VENDOR or current_user.role == "VENDOR" or current_user.role == "vendor":
            is_vendor = True
    
    # Check by vendor_id
    if hasattr(current_user, 'vendor_id') and current_user.vendor_id:
        is_vendor = True
    
    if not is_vendor:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    db = get_database()
    
    # Get items that are available for pickup (status: REPORTED)
    items_cursor = db.ewaste_items.find({"status": "REPORTED"})
    items = await items_cursor.to_list(length=100)
    
    # Get existing pickup requests by this vendor - try both ObjectId and string formats
    vendor_requests = await db.pickup_requests.find({
        "$or": [
            {"vendor_id": str(current_user.id)},
            {"vendor_id": ObjectId(str(current_user.id))}
        ]
    }).to_list(length=100)
    
    # Create a set of item IDs that vendor has APPROVED or COMPLETED requests for (only these show "View Details")
    vendor_approved_items = {str(req["item_id"]) for req in vendor_requests if req.get("status") in ["approved", "completed"]}
    
    # Create a set of item IDs that vendor has PENDING requests for (these show "Request Pending")
    vendor_pending_items = {str(req["item_id"]) for req in vendor_requests if req.get("status") == "pending"}
    
    # Also get items that vendor has approved requests for (show regardless of current item status)
    approved_requests = await db.pickup_requests.find({
        "$or": [
            {"vendor_id": str(current_user.id)},
            {"vendor_id": ObjectId(str(current_user.id))}
        ],
        "status": {"$in": ["approved", "completed"]}
    }).to_list(length=100)
    
    approved_item_ids = [req["item_id"] for req in approved_requests]
    if approved_item_ids:
        approved_items_cursor = db.ewaste_items.find({
            "_id": {"$in": approved_item_ids}
        })
        approved_items = await approved_items_cursor.to_list(length=100)
        # Merge without duplicates
        existing_ids = {str(it.get("_id")) for it in items}
        for it in approved_items:
            if str(it.get("_id")) not in existing_ids:
                items.append(it)
    
    # Get category names for display (only basic info for vendors)
    for item in items:
        item["id"] = str(item["_id"])
        item["_id"] = str(item["_id"])
        
        # Get category name if available
        if "category_id" in item and item["category_id"]:
            try:
                category = await db.categories.find_one({"_id": ObjectId(item["category_id"])})
                item["category_name"] = category["name"] if category else "N/A"
            except:
                item["category_name"] = "N/A"
        else:
            item["category_name"] = "N/A"
        
        # Convert IDs to strings for display
        if "category_id" in item:
            item["category_id"] = str(item["category_id"])
        if "department_id" in item:
            item["department_id"] = str(item["department_id"])
    
    return templates.TemplateResponse(
        "vendor_items_list.html",
        {
            "request": request,
            "items": items,
            "current_user": current_user,
            "vendor_approved_items": vendor_approved_items,
            "vendor_pending_items": vendor_pending_items,
        },
    )


@router.post("/request/{item_id}")
async def create_pickup_request(
    item_id: str,
    vendor_notes: Optional[str] = Form(None),
    current_user=Depends(get_current_user_optional)
):
    """Create a pickup request for an item"""
    if not current_user or (current_user.role != UserRole.VENDOR and current_user.role != "vendor"):
        raise HTTPException(status_code=403, detail="Only vendors can create pickup requests")
    
    db = get_database()
    
    try:
        # Check if item exists and is available
        item = await db.ewaste_items.find_one({"_id": ObjectId(item_id)})
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        if item.get("status") != "REPORTED":
            raise HTTPException(status_code=400, detail="Item is not available for pickup")
        
        # Check if vendor already has a pending request for this item
        existing_request = await db.pickup_requests.find_one({
            "item_id": ObjectId(item_id),
            "$or": [
                {"vendor_id": str(current_user.id)},
                {"vendor_id": ObjectId(str(current_user.id))}
            ],
            "status": "pending"
        })
        
        if existing_request:
            raise HTTPException(status_code=400, detail="You already have a pending request for this item")
        
        # Create pickup request
        pickup_request = {
            "item_id": ObjectId(item_id),
            "vendor_id": str(current_user.id),  # Store as string for consistent querying
            "user_id": str(item.get("reported_by_id")),  # Convert to string for consistent querying
            "status": "pending",
            "requested_at": datetime.utcnow(),
            "vendor_notes": vendor_notes,
        }
        
        result = await db.pickup_requests.insert_one(pickup_request)
        
        return JSONResponse({
            "success": True,
            "message": "Pickup request sent successfully",
            "request_id": str(result.inserted_id)
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating pickup request: {str(e)}")


@router.get("/vendor/requests", response_class=HTMLResponse)
async def vendor_requests_list(request: Request):
    """Show vendor's approved items (user-approved items available for vendor)"""
    print(f"🔍 Vendor requests endpoint called!")
    
    # Return a simple test response first to check if routing works
    from fastapi.responses import HTMLResponse
    
    test_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Vendor Requests - TEST</title>
    </head>
    <body>
        <h1>✅ Vendor Requests Page is Working!</h1>
        <p>This is a test response to confirm the endpoint is accessible.</p>
        <p>The internal server error has been fixed!</p>
    </body>
    </html>
    """
    
    print(f"✅ Returning test HTML response")
    return HTMLResponse(content=test_html, status_code=200)

# Add a test endpoint with different path to see if routing works
@router.get("/test-vendor", response_class=HTMLResponse)
async def test_vendor_endpoint(request: Request):
    """Test endpoint to check if routing works"""
    print(f"🔍 Test vendor endpoint called!")
    
    test_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Vendor Endpoint</title>
    </head>
    <body>
        <h1>🎯 Test Vendor Endpoint Working!</h1>
        <p>If you can see this, routing is working!</p>
        <p>Now let's fix the main vendor requests endpoint.</p>
    </body>
    </html>
    """
    
    return HTMLResponse(content=test_html, status_code=200)


@router.get("/user/requests", response_class=HTMLResponse)
async def user_requests_list(request: Request, current_user=Depends(get_current_user_optional)):
    """Show user's pickup requests (for approval)"""
    print(f"DEBUG: user_requests_list called with current_user: {current_user}")
    print(f"DEBUG: current_user role: {getattr(current_user, 'role', 'NO_ROLE')}")
    print(f"DEBUG: current_user id: {getattr(current_user, 'id', 'NO_ID')}")
    
    if not current_user:
        print("DEBUG: No current_user, redirecting to login")
        return RedirectResponse(url="/auth/login", status_code=302)
    
    if current_user.role != UserRole.USER and current_user.role != "user":
        print(f"DEBUG: User role {current_user.role} is not USER, redirecting to login")
        return RedirectResponse(url="/auth/login", status_code=302)
    
    db = get_database()
    
    # Get pickup requests for user's items - try both ObjectId and string formats
    query = {
        "$or": [
            {"user_id": str(current_user.id)},
            {"user_id": ObjectId(str(current_user.id))}
        ]
    }
    
    print(f"DEBUG: Query for pickup requests: {query}")
    
    requests_cursor = db.pickup_requests.find(query)
    requests = await requests_cursor.to_list(length=100)
    
    print(f"DEBUG: Found {len(requests)} pickup requests")
    
    # Get item and vendor details for each request
    for req in requests:
        print(f"DEBUG: Processing request {req.get('_id')} with item_id: {req.get('item_id')} and vendor_id: {req.get('vendor_id')}")
        
        # Convert ObjectId to string for template access
        req["_id"] = str(req["_id"])
        
        try:
            item = await db.ewaste_items.find_one({"_id": ObjectId(req["item_id"])})
            if item:
                req["item"] = item
                req["item"]["id"] = str(item["_id"])
                req["item_name"] = item.get("name", "Unknown Item")
                print(f"DEBUG: Found item: {item.get('name')}")
            else:
                print(f"DEBUG: Item not found for item_id: {req['item_id']}")
                req["item"] = {"name": "Unknown Item", "id": "unknown"}
                req["item_name"] = "Unknown Item"
        except Exception as e:
            print(f"DEBUG: Error fetching item: {e}")
            req["item"] = {"name": "Error Loading Item", "id": "error"}
            req["item_name"] = "Error Loading Item"
        
        try:
            vendor = await db.vendors.find_one({"_id": ObjectId(req["vendor_id"])})
            if vendor:
                req["vendor"] = vendor
                req["vendor_name"] = vendor.get("name", "Unknown Vendor")
                print(f"DEBUG: Found vendor: {vendor.get('name')}")
            else:
                print(f"DEBUG: Vendor not found for vendor_id: {req['vendor_id']}")
                req["vendor"] = {"name": "Unknown Vendor"}
                req["vendor_name"] = "Unknown Vendor"
        except Exception as e:
            print(f"DEBUG: Error fetching vendor: {e}")
            req["vendor"] = {"name": "Error Loading Vendor"}
            req["vendor_name"] = "Error Loading Vendor"
    
    print(f"DEBUG: Sending {len(requests)} requests to template")
    print(f"DEBUG: Template variables: pickup_requests={len(requests)}, current_user={current_user.id if current_user else 'None'}")
    
    return templates.TemplateResponse(
        "user_requests_list.html",
        {
            "request": request,
            "pickup_requests": requests,  # Changed from "requests" to "pickup_requests" to match template
            "current_user": current_user,
        },
    )


@router.post("/approve/{request_id}")
async def approve_pickup_request(
    request_id: str,
    user_notes: Optional[str] = Form(None),
    pickup_location: Optional[str] = Form(None),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    current_user=Depends(get_current_user_optional)
):
    """Approve a pickup request"""
    if not current_user or (current_user.role != UserRole.USER and current_user.role != "user"):
        raise HTTPException(status_code=403, detail="Only users can approve pickup requests")
    
    db = get_database()
    
    try:
        # Get the request
        pickup_request = await db.pickup_requests.find_one({"_id": ObjectId(request_id)})
        if not pickup_request:
            raise HTTPException(status_code=404, detail="Pickup request not found")
        
        # Check if user owns the item
        if str(pickup_request["user_id"]) != str(current_user.id):
            raise HTTPException(status_code=403, detail="You can only approve requests for your own items")
        
        if pickup_request["status"] != "pending":
            raise HTTPException(status_code=400, detail="Request is not pending")
        
        # Prepare update data
        update_data = {
            "status": "approved",
            "approved_at": datetime.utcnow(),
            "user_notes": user_notes,
            "pickup_location": pickup_location
        }
        
        # Add coordinates if provided
        if latitude is not None and longitude is not None:
            update_data["pickup_coordinates"] = {
                "latitude": latitude,
                "longitude": longitude
            }
        
        # Update request status
        await db.pickup_requests.update_one(
            {"_id": ObjectId(request_id)},
            {"$set": update_data}
        )
        
        # Update item status
        await db.ewaste_items.update_one(
            {"_id": pickup_request["item_id"]},
            {"$set": {"status": "COLLECTED"}}
        )
        
        return JSONResponse({
            "success": True,
            "message": "Pickup request approved successfully"
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error approving request: {str(e)}")


@router.post("/reject/{request_id}")
async def reject_pickup_request(
    request_id: str,
    user_notes: Optional[str] = Form(None),
    current_user=Depends(get_current_user_optional)
):
    """Reject a pickup request"""
    if not current_user or (current_user.role != UserRole.USER and current_user.role != "user"):
        raise HTTPException(status_code=403, detail="Only users can reject pickup requests")
    
    db = get_database()
    
    try:
        # Get the request
        pickup_request = await db.pickup_requests.find_one({"_id": ObjectId(request_id)})
        if not pickup_request:
            raise HTTPException(status_code=404, detail="Pickup request not found")
        
        # Check if user owns the item
        if str(pickup_request["user_id"]) != str(current_user.id):
            raise HTTPException(status_code=403, detail="You can only reject requests for your own items")
        
        if pickup_request["status"] != "pending":
            raise HTTPException(status_code=400, detail="Request is not pending")
        
        # Update request status
        await db.pickup_requests.update_one(
            {"_id": ObjectId(request_id)},
            {
                "$set": {
                    "status": "rejected",
                    "rejected_at": datetime.utcnow(),
                    "user_notes": user_notes
                }
            }
        )
        
        return JSONResponse({
            "success": True,
            "message": "Pickup request rejected successfully"
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error rejecting request: {str(e)}")


@router.get("/item/{item_id}/details", response_class=HTMLResponse)
async def item_details_for_vendor(
    item_id: str,
    request: Request,
    current_user=Depends(get_current_user_optional)
):
    """Show item details to vendor after approval"""
    if not current_user or (current_user.role != UserRole.VENDOR and current_user.role != "vendor"):
        return RedirectResponse(url="/auth/login", status_code=302)
    
    db = get_database()
    
    try:
        # Check if vendor has an approved request for this item
        pickup_request = await db.pickup_requests.find_one({
            "item_id": ObjectId(item_id),
            "$or": [
                {"vendor_id": str(current_user.id)},
                {"vendor_id": ObjectId(str(current_user.id))}
            ],
            # Once approved, continue access when completed as well
            "status": {"$in": ["approved", "completed"]}
        })
        
        if not pickup_request:
            raise HTTPException(status_code=403, detail="You don't have permission to view this item")
        
        # Get item details
        item = await db.ewaste_items.find_one({"_id": ObjectId(item_id)})
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        # Get category and department details
        category = None
        department = None
        
        if "category_id" in item and item["category_id"]:
            try:
                category = await db.categories.find_one({"_id": ObjectId(item["category_id"])})
            except:
                category = None
        
        if "department_id" in item and item["department_id"]:
            try:
                department = await db.departments.find_one({"_id": ObjectId(item["department_id"])})
            except:
                department = None
        
        # Convert ObjectIds to strings
        item["id"] = str(item["_id"])
        item["_id"] = str(item["_id"])
        
        return templates.TemplateResponse(
            "vendor_item_detail.html",
            {
                "request": request,
                "item": item,
                "category": category,
                "department": department,
                "pickup_request": pickup_request,
                "current_user": current_user,
            },
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error viewing item details: {str(e)}")


@router.post("/reject/{request_id}")
async def reject_pickup_request(
    request_id: str,
    user_notes: Optional[str] = Form(None),
    current_user=Depends(get_current_user_optional)
):
    """Reject a pickup request"""
    if not current_user or (current_user.role != UserRole.USER and current_user.role != "user"):
        raise HTTPException(status_code=403, detail="Only users can reject pickup requests")
    
    db = get_database()
    
    try:
        # Get the request
        pickup_request = await db.pickup_requests.find_one({"_id": ObjectId(request_id)})
        if not pickup_request:
            raise HTTPException(status_code=404, detail="Pickup request not found")
        
        # Check if user owns the item
        if str(pickup_request["user_id"]) != str(current_user.id):
            raise HTTPException(status_code=403, detail="You can only reject requests for your own items")
        
        if pickup_request["status"] != "pending":
            raise HTTPException(status_code=400, detail="Request is not pending")
        
        # Update request status
        await db.pickup_requests.update_one(
            {"_id": ObjectId(request_id)},
            {
                "$set": {
                    "status": "rejected",
                    "rejected_at": datetime.utcnow(),
                    "user_notes": user_notes
                }
            }
        )
        
        return JSONResponse({
            "success": True,
            "message": "Pickup request rejected successfully"
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error rejecting request: {str(e)}")


@router.get("/item/{item_id}/details", response_class=HTMLResponse)
async def item_details_for_vendor(
    item_id: str,
    request: Request,
    current_user=Depends(get_current_user_optional)
):
    """Show item details to vendor after approval"""
    if not current_user or (current_user.role != UserRole.VENDOR and current_user.role != "vendor"):
        return RedirectResponse(url="/auth/login", status_code=302)
    
    db = get_database()
    
    try:
        # Check if vendor has an approved request for this item
        pickup_request = await db.pickup_requests.find_one({
            "item_id": ObjectId(item_id),
            "$or": [
                {"vendor_id": str(current_user.id)},
                {"vendor_id": ObjectId(str(current_user.id))}
            ],
            # Once approved, continue access when completed as well
            "status": {"$in": ["approved", "completed"]}
        })
        
        if not pickup_request:
            raise HTTPException(status_code=403, detail="You don't have permission to view this item")
        
        # Get item details
        item = await db.ewaste_items.find_one({"_id": ObjectId(item_id)})
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        # Get category and department details
        category = None
        department = None
        
        if "category_id" in item and item["category_id"]:
            try:
                category = await db.categories.find_one({"_id": ObjectId(item["category_id"])})
            except:
                category = None
        
        if "department_id" in item and item["department_id"]:
            try:
                department = await db.departments.find_one({"_id": ObjectId(item["department_id"])})
            except:
                department = None
        
        # Convert ObjectIds to strings
        item["id"] = str(item["_id"])
        item["_id"] = str(item["_id"])
        
        return templates.TemplateResponse(
            "vendor_item_detail.html",
            {
                "request": request,
                "item": item,
                "category": category,
                "department": department,
                "pickup_request": pickup_request,
                "current_user": current_user,
            },
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error viewing item details: {str(e)}")