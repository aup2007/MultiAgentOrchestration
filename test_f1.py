import os
from f1_agent import f1_node
from dotenv import load_dotenv


load_dotenv()  
api_key = os.getenv("GROQ_API_KEY")


def run_test():
    initial_state = {
        "messages": [],
        "query": "What was Max Verstappen's fastest lap in the 2024 Monaco GP?",
        "user_role": "admin",
        "final_response": ""
    }
    
    print("Starting F1 Node Test...")
    result = f1_node(initial_state)
    
    print("\n--- FINAL TWG RESPONSE ---")
    print(result["final_response"])

if __name__ == "__main__":
    run_test()