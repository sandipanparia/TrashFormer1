from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Dict, Optional, Union
from datetime import datetime, timedelta
from bson import ObjectId

from ..database import get_database
from ..enums import ItemStatus, CategoryType, UserRole
from ..utils import get_current_user_optional
from ..models import User, VendorUser

router = APIRouter(prefix="/analytics", tags=["analytics"])
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def analytics_home(request: Request, current_user=Depends(get_current_user_optional)):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=302)
    
    # Determine user type for analytics
    user_type = "user"
    if current_user.__class__.__name__ == 'VendorUser':
        user_type = "vendor"
    elif hasattr(current_user, 'role') and current_user.role == UserRole.VENDOR:
        user_type = "vendor"
    elif hasattr(current_user, 'vendor_id') and current_user.vendor_id:
        user_type = "vendor"
    
    return templates.TemplateResponse(
        "analytics.html", 
        {
            "request": request, 
            "current_user": current_user,
            "user_type": user_type
        }
    )


@router.get("/summary", response_class=JSONResponse)
async def analytics_summary(request: Request, current_user=Depends(get_current_user_optional)):
    """Get comprehensive analytics summary data based on user role"""
    if not current_user:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})
    
    db = get_database()
    
    try:
        # Determine user type
        is_vendor = (
            current_user.__class__.__name__ == 'VendorUser' or
            (hasattr(current_user, 'role') and current_user.role == UserRole.VENDOR) or
            (hasattr(current_user, 'vendor_id') and current_user.vendor_id)
        )
        
        user_id_str = str(current_user.id)
        
        if is_vendor:
            # Vendor Analytics - show data related to available items they can collect
            vendor_id_str = str(current_user.vendor_id) if current_user.vendor_id else user_id_str
            
            # Get all available e-waste items that vendors can potentially collect
            # These are items that are reported but not yet assigned to any vendor
            available_items_filter = {
                "status": {"$in": ["REPORTED", "COLLECTED", "IN_STORAGE"]},
                # Exclude items that already have approved/completed pickup requests
                "_id": {"$nin": []}  # Will be populated below
            }
            
            # Get items that already have pickup requests (to exclude them from available items)
            existing_pickup_items = await db.pickup_requests.find({
                "status": {"$in": ["approved", "completed", "pending"]}
            }).to_list(length=None)
            
            existing_item_ids = [req["item_id"] for req in existing_pickup_items]
            if existing_item_ids:
                available_items_filter["_id"]["$nin"] = [ObjectId(item_id) for item_id in existing_item_ids]
            
            # Get total available items
            total_available_items = await db.ewaste_items.count_documents(available_items_filter)
            
            # Get vendor's currently assigned items (for comparison)
            vendor_pickup_requests = await db.pickup_requests.find({
                "vendor_id": vendor_id_str,
                "status": {"$in": ["approved", "completed"]}
            }).to_list(length=None)
            
            vendor_item_ids = [req["item_id"] for req in vendor_pickup_requests]
            vendor_items_filter = {"_id": {"$in": [ObjectId(item_id) for item_id in vendor_item_ids]}} if vendor_item_ids else {"_id": {"$in": []}}
            total_assigned_items = await db.ewaste_items.count_documents(vendor_items_filter)
            
            # Use available items for main statistics
            total_items = total_available_items
            
            # Get status breakdown for available items (items vendors can collect)
            status_counts = {}
            for status in ["REPORTED", "COLLECTED", "IN_STORAGE"]:
                count = await db.ewaste_items.count_documents({
                    **available_items_filter,
                    "status": status
                })
                status_counts[status.lower()] = count
            
            # Add assigned items count for comparison
            status_counts["assigned"] = total_assigned_items
            
            # Get vendor's pickup request status breakdown
            pickup_status_counts = {}
            for status in ["pending", "approved", "rejected", "completed"]:
                count = await db.pickup_requests.count_documents({
                    "vendor_id": vendor_id_str,
                    "status": status
                })
                pickup_status_counts[status] = count
            
            # Get category breakdown for available items
            categories = await db.categories.find().to_list(length=None)
            category_counts = {}
            for category in categories:
                # Try both string and ObjectId formats for category_id
                count = await db.ewaste_items.count_documents({
                    **available_items_filter,
                    "$or": [
                        {"category_id": str(category["_id"])},
                        {"category_id": category["_id"]}
                    ]
                })
                if count > 0:  # Only add categories that have items
                    category_counts[category["name"]] = count
            
            # If no categories found, add a default category
            if not category_counts:
                category_counts["General E-Waste"] = total_items
            
            # Get monthly trends for available items
            monthly_data = {}
            for i in range(6):
                date = datetime.now() - timedelta(days=30*i)
                start_date = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                if i == 0:
                    end_date = datetime.now()
                else:
                    end_date = (date.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
                
                count = await db.ewaste_items.count_documents({
                    **available_items_filter,
                    "reported_date": {"$gte": start_date, "$lte": end_date}
                })
                month_key = start_date.strftime("%b %Y")
                monthly_data[month_key] = count
            
            # Get recent activity for available items
            recent_items = await db.ewaste_items.find(available_items_filter).sort("reported_date", -1).limit(10).to_list(length=None)
            recent_activity = []
            for item in recent_items:
                recent_activity.append({
                    "id": str(item["_id"]),
                    "name": item["name"],
                    "status": item["status"],
                    "reported_date": item["reported_date"].strftime("%Y-%m-%d") if item.get("reported_date") else "N/A"
                })
            
            # Calculate potential impact metrics for available items
            # Since these are available items, we calculate potential impact if they were all processed
            total_weight = await db.ewaste_items.aggregate([
                {"$match": available_items_filter},
                {"$group": {"_id": None, "total": {"$sum": "$weight_kg"}}}
            ]).to_list(length=None)
            total_weight_kg = total_weight[0]["total"] if total_weight and total_weight[0]["total"] else 0
            
            if total_weight_kg == 0 and total_items > 0:
                avg_weight_per_item = 5.0
                total_weight_kg = total_items * avg_weight_per_item
            
            # Calculate potential environmental impact if all available items were processed
            potential_co2_saved = total_weight_kg * 2.5
            potential_hazardous_avoided = total_weight_kg * 0.3
            
            # Calculate completion rate based on assigned vs available items
            completion_rate = (total_assigned_items / total_items * 100) if total_items > 0 else 0
            
            return {
                "totalItems": total_items,
                "itemsByStatus": status_counts,
                "itemsByCategoryType": category_counts,
                "monthlyReported": monthly_data,
                "recycledWeightKg": round(total_weight_kg, 2),
                "co2SavedKg": round(potential_co2_saved, 2),
                "hazardousMaterialsAvoided": round(potential_hazardous_avoided, 2),
                "completionRate": round(completion_rate, 1),
                "totalPickupRequests": sum(pickup_status_counts.values()),
                "pickupRequestsByStatus": pickup_status_counts,
                "recentActivity": recent_activity,
                "userType": "vendor",
                "totalAssignedItems": total_assigned_items,
                "totalAvailableItems": total_available_items
            }
            
        else:
            # User Analytics - show data for items they reported
            # Get items reported by this user - use string format since that's how it's stored
            user_items_filter = {"reported_by_id": user_id_str}
            
            # Debug: Print the user filter being used
            print(f"User Analytics - User ID: {user_id_str}, Filter: {user_items_filter}")
            
            # Also check if we need to try ObjectId format
            test_count = await db.ewaste_items.count_documents(user_items_filter)
            if test_count == 0:
                # Try ObjectId format if string format returns 0
                user_items_filter = {"reported_by_id": ObjectId(user_id_str)}
                print(f"User Analytics - Trying ObjectId format: {user_items_filter}")
                test_count = await db.ewaste_items.count_documents(user_items_filter)
                if test_count == 0:
                    # If still 0, revert to string format
                    user_items_filter = {"reported_by_id": user_id_str}
                    print(f"User Analytics - Reverting to string format: {user_items_filter}")
            
            total_items = await db.ewaste_items.count_documents(user_items_filter)
            
            # Get status breakdown for user's items
            status_counts = {}
            for status in ["REPORTED", "COLLECTED", "IN_STORAGE", "SENT_TO_VENDOR", "RECYCLED", "DISPOSED"]:
                count = await db.ewaste_items.count_documents({
                    **user_items_filter,
                    "status": status
                })
                status_counts[status.lower()] = count
            
            # Get category breakdown for user's items
            categories = await db.categories.find().to_list(length=None)
            category_counts = {}
            
            # Debug: Print total user items found
            print(f"User Analytics - Total user items: {total_items}")
            
            # Debug: Get all user items to see their category_id values
            user_items = await db.ewaste_items.find(user_items_filter).to_list(length=None)
            print(f"User Analytics - User items found: {len(user_items)}")
            for item in user_items:
                print(f"  Item: {item.get('name', 'N/A')}, category_id: {item.get('category_id')}, type: {type(item.get('category_id'))}")
            
            for category in categories:
                # Try both string and ObjectId formats for category_id
                count = await db.ewaste_items.count_documents({
                    **user_items_filter,
                    "$or": [
                        {"category_id": str(category["_id"])},
                        {"category_id": category["_id"]}
                    ]
                })
                if count > 0:  # Only add categories that have items
                    category_counts[category["name"]] = count
                    print(f"User Analytics - Category '{category['name']}': {count} items")
            
            # If no categories found, add a default category
            if not category_counts:
                category_counts["General E-Waste"] = total_items
                print(f"User Analytics - No specific categories found, using default: {total_items} items")
            
            # Debug: Print final category counts
            print(f"User Analytics - Final category counts: {category_counts}")
            
            # Get monthly trends for user's items
            monthly_data = {}
            for i in range(6):
                date = datetime.now() - timedelta(days=30*i)
                start_date = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                if i == 0:
                    end_date = datetime.now()
                else:
                    end_date = (date.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
                
                count = await db.ewaste_items.count_documents({
                    **user_items_filter,
                    "reported_date": {"$gte": start_date, "$lte": end_date}
                })
                month_key = start_date.strftime("%b %Y")
                monthly_data[month_key] = count
            
            # Get recent activity for user's items
            recent_items = await db.ewaste_items.find(user_items_filter).sort("reported_date", -1).limit(10).to_list(length=None)
            recent_activity = []
            for item in recent_items:
                recent_activity.append({
                    "id": str(item["_id"]),
                    "name": item["name"],
                    "status": item["status"],
                    "reported_date": item["reported_date"].strftime("%Y-%m-%d") if item.get("reported_date") else "N/A"
                })
            
            # Calculate completion rate for user's items
            completed_items = status_counts.get("disposed", 0) + status_counts.get("recycled", 0)
            completion_rate = (completed_items / total_items * 100) if total_items > 0 else 0
            
            # Calculate impact metrics for user's items
            total_weight = await db.ewaste_items.aggregate([
                {"$match": user_items_filter},
                {"$group": {"_id": None, "total": {"$sum": "$weight_kg"}}}
            ]).to_list(length=None)
            total_weight_kg = total_weight[0]["total"] if total_weight and total_weight[0]["total"] else 0
            
            if total_weight_kg == 0 and total_items > 0:
                avg_weight_per_item = 5.0
                total_weight_kg = total_items * avg_weight_per_item
            
            recycled_items = status_counts.get("recycled", 0) + status_counts.get("disposed", 0)
            recycled_weight = (recycled_items / total_items * total_weight_kg) if total_items > 0 else 0
            
            co2_saved = recycled_weight * 2.5
            hazardous_avoided = recycled_weight * 0.3
            
            if recycled_weight == 0 and total_items > 0:
                recycled_weight = total_items * 2.0
                co2_saved = recycled_weight * 2.5
                hazardous_avoided = recycled_weight * 0.3
            
            return {
                "totalItems": total_items,
                "itemsByStatus": status_counts,
                "itemsByCategoryType": category_counts,
                "monthlyReported": monthly_data,
                "recycledWeightKg": round(recycled_weight, 2),
                "co2SavedKg": round(co2_saved, 2),
                "hazardousMaterialsAvoided": round(hazardous_avoided, 2),
                "completionRate": round(completion_rate, 1),
                "recentActivity": recent_activity,
                "userType": "user"
            }
        
    except Exception as e:
        print(f"Analytics error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch analytics data: {str(e)}"}
        )

