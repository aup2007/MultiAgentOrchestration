import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))

def ensure_f1_partition(year: int, engine):
    """
    Checks Neon for the F1 infrastructure and creates 
    the year partition if it's missing.
    """
    with engine.connect() as conn:
        # 1. First, make sure the Master Parent exists (The 'House')
        # Without this, the partition command throws the 'UndefinedTable' error
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS f1_telemetry (
                id SERIAL,
                year INT NOT NULL,
                event_name TEXT,
                driver TEXT,
                team TEXT,
                lap_number INT,
                lap_time_seconds FLOAT,
                PRIMARY KEY (id, year)
            ) PARTITION BY RANGE (year);
        """))
        conn.commit()

        # 2. Now, create the specific Year Partition (The 'Room')
        partition_name = f"f1_laps_{year}"
        
        exists = conn.execute(text(
            "SELECT EXISTS (SELECT FROM pg_tables WHERE tablename = :tname);"
        ), {"tname": partition_name}).scalar()
        
        if not exists:
            print(f">>> [DB] Creating partition: {partition_name}")
            conn.execute(text(f"""
                CREATE TABLE {partition_name} PARTITION OF f1_telemetry
                FOR VALUES FROM ({year}) TO ({year + 1});
            """))
            conn.commit()
        else:
            print(f">>> [DB] Partition {partition_name} is ready.")
def get_engine():
    return engine