import motor.motor_asyncio
from bson import ObjectId
import asyncio

# MongoDB connection settings
MONGODB_URL = "mongodb://localhost:27017"
DATABASE_NAME = "ewaste_management"

# Global variables for database connection
client = None
database = None


async def connect_to_mongo():
    """Connect to MongoDB"""
    global client, database
    try:
        client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URL)
        database = client[DATABASE_NAME]
        
        # Test the connection
        await client.admin.command('ping')
        print("✅ Connected to MongoDB:", DATABASE_NAME)
        print("✅ MongoDB connection test successful")
        
    except Exception as e:
        print("❌ MongoDB connection failed:", str(e))
        raise e


async def close_mongo_connection():
    """Close MongoDB connection"""
    global client
    if client:
        client.close()
        print("✅ MongoDB connection closed")


def get_database():
    """Get the database instance"""
    return database


async def init_db():
    """Initialize database with indexes and sample data"""
    try:
        db = get_database()
        
        # Create indexes with error handling
        try:
            await db.users.create_index("username", unique=True)
        except Exception:
            pass  # Index might already exist
            
        try:
            await db.users.create_index("email", unique=True)
        except Exception:
            pass
            
        try:
            await db.vendor_users.create_index("username", unique=True)
        except Exception:
            pass
            
        try:
            await db.vendor_users.create_index("email", unique=True)
        except Exception:
            pass
            
        try:
            await db.ewaste_items.create_index("serial_number", unique=True)
        except Exception:
            pass
            
        try:
            await db.ewaste_items.create_index("reported_date")
        except Exception:
            pass
        
        # Check if collections are empty before adding sample data
        users_count = await db.users.count_documents({})
        vendors_count = await db.vendors.count_documents({})
        departments_count = await db.departments.count_documents({})
        categories_count = await db.categories.count_documents({})
        
        if users_count == 0 and vendors_count == 0 and departments_count == 0 and categories_count == 0:
            await create_sample_data()
            print("✅ Sample data created successfully")
        else:
            print("✅ Database already contains data, skipping sample data creation")
            
        print("✅ Database initialization complete")
            
    except Exception as e:
        print("❌ Database initialization failed:", str(e))
        # Don't raise the error, just log it
        pass


async def create_sample_data():
    """Create sample data for the application"""
    db = get_database()
    
    # Sample departments
    departments_data = [
        {"name": "IT Department", "description": "Information Technology Department"},
        {"name": "HR Department", "description": "Human Resources Department"},
        {"name": "Finance Department", "description": "Finance and Accounting Department"},
        {"name": "Operations Department", "description": "Operations and Logistics Department"}
    ]
    
    for dept_data in departments_data:
        try:
            await db.departments.insert_one(dept_data)
        except Exception:
            # Skip if already exists
            pass
    
    # Sample categories
    categories_data = [
        {"name": "Computers", "type": "ELECTRONICS", "description": "Desktop and laptop computers"},
        {"name": "Mobile Devices", "type": "ELECTRONICS", "description": "Smartphones and tablets"},
        {"name": "Printers", "type": "ELECTRONICS", "description": "Printers and scanners"},
        {"name": "Batteries", "type": "HAZARDOUS", "description": "Lithium and lead-acid batteries"},
        {"name": "Cables", "type": "ELECTRONICS", "description": "Power and data cables"},
        {"name": "Monitors", "type": "ELECTRONICS", "description": "Computer monitors and displays"}
    ]
    
    for cat_data in categories_data:
        try:
            await db.categories.insert_one(cat_data)
        except Exception:
            # Skip if already exists
            pass
    
    # Sample vendors
    vendors_data = [
        {
            "name": "Green Recycle Solutions",
            "contact_person": "John Smith",
            "phone": "+1-555-0101",
            "email": "info@greenrecycle.example",
            "license_no": "GRS-2024-001",
            "address": "123 Green Street, Eco City, EC 12345",
            "is_verified": True
        },
        {
            "name": "EcoTech Disposal",
            "contact_person": "Sarah Johnson",
            "phone": "+1-555-0102",
            "email": "contact@ecotech.example",
            "license_no": "ETD-2024-002",
            "address": "456 Eco Avenue, Green Town, GT 67890",
            "is_verified": False
        }
    ]
    
    for vendor_data in vendors_data:
        try:
            await db.vendors.insert_one(vendor_data)
        except Exception:
            # Skip if already exists
            pass

