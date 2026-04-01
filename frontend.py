import streamlit as st
import requests

API_URL = "http://localhost:8000"
st.set_page_config(page_title="TWG Multi-Agent Router", layout="wide")

if "token" not in st.session_state:
    st.session_state["token"] = None

if st.session_state["token"] is None:
    st.title("TWG Global - Secure Login")
    username = st.text_input("Username (e.g., mark_walter, chelsea_scout)")
    password = st.text_input("Password", type="password")
    
    if st.button("Authenticate"):
        res = requests.post(f"{API_URL}/token", data={"username": username, "password": password})
        if res.status_code == 200:
            st.session_state["token"] = res.json()["access_token"]
            st.rerun()
        else:
            st.error("Authentication Failed")
else:
    st.title("Sports Intelligence Router")
    st.sidebar.button("Logout", on_click=lambda: st.session_state.update(token=None))
    
    query = st.chat_input("Query a sector dataset...")
    if query:
        st.chat_message("user").write(query)
        headers = {"Authorization": f"Bearer {st.session_state['token']}"}
        
        with st.chat_message("assistant"):
            # Create a placeholder for the live updates
            status_placeholder = st.empty()
            response_placeholder = st.empty()
            status_placeholder.caption("Packaging query for backend...")
            
            # Add stream=True to keep the connection open and read chunks
            res = requests.post(f"{API_URL}/chat", json={"query": query}, headers=headers, stream=True)
            
            final_reply = ""
            final_domain = ""

            if res.status_code == 200:
                # Iterate over the raw bytes coming from the SSE backend
                for line in res.iter_lines():
                    if line:
                        # Decode bytes to string and strip the "data: " prefix
                        decoded_line = line.decode('utf-8')
                        if decoded_line.startswith("data: "):
                            data_str = decoded_line.replace("data: ", "")
                            import json
                            data = json.loads(data_str)
                            
                            # Handle potential backend errors
                            if "error" in data:
                                st.error(f"Agent Error: {data['error']}")
                                break
                            
                            # Update the UI with the live node status
                            status_placeholder.caption(f"🔄 {data['status']}")
                            
                            # Capture the final text if it's populated
                            if data.get("reply"):
                                final_reply = data["reply"]
                                final_domain = data["domain"]
                
                # Once the stream finishes, clear the status and show the final answer
                status_placeholder.empty()
                response_placeholder.write(final_reply)
                st.caption(f"Domain Routed: {final_domain}")
                
            else:
                st.error("API Error")