import sqlite3

def show_database_info():
    try:
        conn = sqlite3.connect('ewaste.db')
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        print("📋 Database Tables:")
        for table in tables:
            table_name = table[0]
            print(f"   • {table_name}")
            
            # Show table structure
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            print(f"     Columns:")
            for col in columns:
                col_name, col_type, not_null, default_val, pk = col[1], col[2], col[3], col[4], col[5]
                pk_mark = " 🔑" if pk else ""
                print(f"       - {col_name}: {col_type}{pk_mark}")
            print()
        
        conn.close()
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    show_database_info()



