import os
from dotenv import load_dotenv
from sqlalchemy import text
from db_utils import engine

load_dotenv()

def initialize_dodgers_tables():
    print(">>> ⚾ Initializing Dodgers Database Schema in Neon...")
    
    # 1. Roster Table
    create_roster = """
    CREATE TABLE IF NOT EXISTS dodgers_roster (
        mlbam_id INTEGER PRIMARY KEY,
        fg_id TEXT,
        name_first TEXT,
        name_last TEXT,
        position TEXT,
        season_year INTEGER
    );
    """
    
    # 2. Batting Table
    create_batting = """
    CREATE TABLE IF NOT EXISTS dodgers_batting_season (
        id SERIAL PRIMARY KEY,
        season_year INTEGER NOT NULL,
        name TEXT,
        team TEXT,
        g INTEGER,
        hr INTEGER,
        avg DOUBLE PRECISION,
        ops DOUBLE PRECISION,
        wrc_plus DOUBLE PRECISION,
        war DOUBLE PRECISION
    );
    """
    
    # 3. Pitching Table
    create_pitching = """
    CREATE TABLE IF NOT EXISTS dodgers_pitching_season (
        id SERIAL PRIMARY KEY,
        season_year INTEGER NOT NULL,
        name TEXT,
        team TEXT,
        w INTEGER,
        l INTEGER,
        era DOUBLE PRECISION,
        so INTEGER,
        whip DOUBLE PRECISION,
        war DOUBLE PRECISION
    );
    """
    
    # 4. Game Logs Table
    create_game_logs = """
    CREATE TABLE IF NOT EXISTS dodgers_game_logs (
        id SERIAL PRIMARY KEY,
        season_year INTEGER NOT NULL,
        date TEXT,
        opponent TEXT,
        w_l TEXT,
        r INTEGER,
        ra INTEGER,
        win_pitcher TEXT,
        streak TEXT
    );
    """
    
    # 5. Statcast Table
    create_statcast = """
    CREATE TABLE IF NOT EXISTS dodgers_statcast (
        id SERIAL PRIMARY KEY,
        season_year INTEGER,
        game_date DATE,
        player_name TEXT,
        batter INTEGER,
        pitcher INTEGER,
        pitch_type TEXT,
        release_speed DOUBLE PRECISION,
        events TEXT,
        launch_speed DOUBLE PRECISION,
        launch_angle DOUBLE PRECISION,
        hit_distance_sc DOUBLE PRECISION
    );
    """

    try:
        with engine.begin() as conn:
            conn.execute(text(create_roster))
            conn.execute(text(create_batting))
            conn.execute(text(create_pitching))
            conn.execute(text(create_game_logs))
            conn.execute(text(create_statcast))
            
        print(">>> ✅ All Dodgers tables created successfully in Neon!")
    except Exception as e:
        print(f">>> ❌ Error creating tables: {e}")

if __name__ == "__main__":
    initialize_dodgers_tables()