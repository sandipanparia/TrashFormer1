from datetime import date
from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os

from .database import connect_to_mongo, close_mongo_connection, init_db, get_database
from .enums import ItemStatus
from .routers import items, vendors, schedules, reports, analytics, campaigns, auth, pickup_requests
from .utils import get_current_user_optional


app = FastAPI(title="Smart E‑Waste Management System (MVP)")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def on_startup():
    await connect_to_mongo()
    await init_db()
    # Ensure uploads directory exists
    os.makedirs("static/uploads", exist_ok=True)


@app.on_event("shutdown")
async def on_shutdown():
    await close_mongo_connection()



@app.get("/", response_class=HTMLResponse)
async def index(request: Request, current_user=Depends(get_current_user_optional)):
    db = get_database()
    
    # Get counts from MongoDB
    total_count = await db.ewaste_items.count_documents({})
    reported = await db.ewaste_items.count_documents({"status": ItemStatus.REPORTED})
    recycled = await db.ewaste_items.count_documents({"status": ItemStatus.RECYCLED})
    disposed = await db.ewaste_items.count_documents({"status": ItemStatus.DISPOSED})
    
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "total_count": total_count,
            "reported": reported,
            "recycled": recycled,
            "disposed": disposed,
            "current_user": current_user,
        },
    )


app.include_router(auth.router)
app.include_router(items.router)
app.include_router(vendors.router)
app.include_router(schedules.router)
app.include_router(reports.router)
app.include_router(analytics.router)
app.include_router(campaigns.router)
app.include_router(pickup_requests.router)

