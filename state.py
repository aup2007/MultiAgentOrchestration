from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage
import operator

class AgentState(TypedDict):


    messages: Annotated[Sequence[BaseMessage], operator.add]
    query: str
    user_role: str  
    domain_detected: str  
    final_response: str