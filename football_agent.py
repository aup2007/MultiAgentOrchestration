from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_openai import ChatGroq # Or ChatGroq
from state import AgentState

db = SQLDatabase.from_uri("sqlite:///transfermarkt.db")
llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0)

# Create the dedicated SQL Agent
soccer_sql_executor = create_sql_agent(llm, db=db, agent_type="openai-tools", verbose=True)

def soccer_node(state: AgentState):
    """Executes the soccer query against the Transfermarkt database."""
    print("--- ENTERING SOCCER AGENT ---")
    query = state["query"]
    
    # Run the SQL agent
    result = soccer_sql_executor.invoke({"input": query})
    
    return {"final_response": result["output"]}