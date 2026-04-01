# reset_db.py
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

def reset_f1_database():
    print(">>> Loading environment variables...")
    load_dotenv()
    
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not found in .env")
        return

    print(">>> Connecting to Neon PostgreSQL...")
    engine = create_engine(db_url)

    try:
        with engine.connect() as conn:
            # DROP TABLE CASCADE completely deletes the parent table
            # AND all associated child partitions (e.g., f1_laps_2024).
            print(">>> Dropping old f1_telemetry table and all partitions...")
            conn.execute(text("DROP TABLE IF EXISTS f1_telemetry CASCADE;"))
            conn.commit()
            
            print(">>> SUCCESS: Database reset complete.")
            print(">>> The new schema will be created automatically the next time you query an F1 race.")
    
    except Exception as e:
        print(f">>> ERROR resetting database: {e}")

if __name__ == "__main__":
    
    # SECURITY WARNING: This will permanently delete all cached F1 data in your database.
    confirm = input("Type 'DELETE' to confirm you want to wipe the F1 database: ")
    
    if confirm == 'DELETE':
        reset_f1_database()
    else:
        print("Operation cancelled.")