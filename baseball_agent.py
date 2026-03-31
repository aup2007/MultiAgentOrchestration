from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_openai import ChatGroq
from state import AgentState

db = SQLDatabase.from_uri("sqlite:///lahman.db")
llm = ChatGroq(model="gpt-4o-mini", temperature=0)

baseball_sql_executor = create_sql_agent(llm, db=db, agent_type="openai-tools", verbose=True)

def baseball_node(state: AgentState):
    """Executes the baseball query against the Lahman database."""
    print("--- ENTERING BASEBALL AGENT ---")
    result = baseball_sql_executor.invoke({"input": state["query"]})
    return {"final_response": result["output"]}