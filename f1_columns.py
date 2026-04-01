import fastf1
import pandas as pd

def inspect_fastf1_columns(year: int, location: str, session_type: str):
    print(f"Fetching data for {year} {location} {session_type}...")
    
    # Enable cache to speed up repeated runs (creates a 'f1_cache' folder in your directory)
    fastf1.Cache.enable_cache('f1_cache') 
    
    try:
        # Load the session
        session = fastf1.get_session(year, location, session_type)
        
        # Load laps data (we don't need high-res telemetry or weather just to see lap columns)
        session.load(laps=True, telemetry=False, weather=False)
        
        laps_df = session.laps
        
        print("\n--- FASTF1 LAPS DATAFRAME COLUMNS ---")
        
        # Create a clean summary dataframe showing Column Name, Data Type, and a Sample Value
        summary_df = pd.DataFrame({
            'Data Type': laps_df.dtypes,
            'Sample Value (Lap 1)': laps_df.iloc[0] if not laps_df.empty else None
        })
        
        # Print all rows without truncating
        pd.set_option('display.max_rows', None)
        print(summary_df)
        
        print("\nTotal Columns:", len(laps_df.columns))
        
    except Exception as e:
        print(f"Error fetching data: {e}")

if __name__ == "__main__":
    # Example: 2024 Monaco Grand Prix (Race)
    # You can change these to test different events
    inspect_fastf1_columns(2020, 'Monaco', 'R')