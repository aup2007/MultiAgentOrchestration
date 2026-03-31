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
            res = requests.post(f"{API_URL}/chat", json={"query": query}, headers=headers)
            
        if res.status_code == 200:
            data = res.json()
            st.chat_message("assistant").write(data["reply"])
            st.caption(f"Domain Routed: {data['domain']}")
        else:
            st.error("API Error")