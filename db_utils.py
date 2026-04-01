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
                time_seconds FLOAT,
                driver TEXT,
                driver_number TEXT,
                lap_time_seconds FLOAT,
                lap_number INT,
                stint INT,
                pit_out_time_seconds FLOAT,
                pit_in_time_seconds FLOAT,
                sector1_time_seconds FLOAT,
                sector2_time_seconds FLOAT,
                sector3_time_seconds FLOAT,
                sector1_session_time_seconds FLOAT,
                sector2_session_time_seconds FLOAT,
                sector3_session_time_seconds FLOAT,
                speed_i1 FLOAT,
                speed_i2 FLOAT,
                speed_fl FLOAT,
                speed_st FLOAT,
                is_personal_best BOOLEAN,
                compound TEXT,
                tyre_life FLOAT,
                fresh_tyre BOOLEAN,
                team TEXT,
                lap_start_time_seconds FLOAT,
                lap_start_date TIMESTAMP,
                track_status TEXT,
                position FLOAT,
                deleted BOOLEAN,
                deleted_reason TEXT,
                fastf1_generated BOOLEAN,
                is_accurate BOOLEAN,
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