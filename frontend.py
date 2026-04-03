import streamlit as st
import requests
import json
import logging

logger = logging.getLogger(__name__)

API_URL = "http://localhost:8000"
st.set_page_config(
    page_title="TWG Multi-Agent Router",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# STYLING
# ============================================================================

st.markdown("""
<style>
    .node-executing { color: #FFA500; font-weight: bold; }
    .node-completed { color: #28A745; font-weight: bold; }
    .node-error { color: #DC3545; font-weight: bold; }
    .token-stream { font-family: 'Courier New', monospace; line-height: 1.6; }
    .thought-trace {
        background-color: #f8f9fa;
        border-left: 4px solid #0066cc;
        padding: 10px;
        border-radius: 4px;
        margin: 5px 0;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# SESSION STATE
# ============================================================================

if "token" not in st.session_state:
    st.session_state["token"] = None

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []

# ============================================================================
# LOGIN PAGE
# ============================================================================

if st.session_state["token"] is None:
    st.title("🏆 TWG Global - Secure Login")
    st.markdown("*Sports Intelligence Platform with Real-Time Streaming*")

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        username = st.text_input(
            "Username",
            placeholder="e.g., mark_walter, atharv_admin, chelsea_scout"
        )
        password = st.text_input("Password", type="password")

        if st.button("🔐 Authenticate", use_container_width=True):
            res = requests.post(
                f"{API_URL}/token",
                data={"username": username, "password": password}
            )
            if res.status_code == 200:
                st.session_state["token"] = res.json()["access_token"]
                st.rerun()
            else:
                st.error("❌ Authentication Failed")

    st.divider()
    st.markdown("""
    ### Demo Credentials:
    - **Owner**: mark_walter / password123
    - **Admin**: atharv_admin / nyu2025
    - **Scout**: chelsea_scout / football24
    """)

# ============================================================================
# MAIN APP (Authenticated)
# ============================================================================

else:
    st.title("🏆 TWG Sports Intelligence Platform")
    st.markdown("*Real-time Multi-Agent Analytics with Live Thought Trace*")

    # Sidebar
    with st.sidebar:
        st.markdown("### ⚙️ Settings")

        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.token = None
            st.rerun()

        st.divider()
        st.markdown("### 📊 About")
        st.info("""
        **Dual-Stream SSE Architecture:**
        - 🧠 Updates: Node execution trace
        - 💬 Messages: LLM token streaming

        **Real-Time Features:**
        - Live thought trace (st.status)
        - Incremental token rendering
        - Zero-latency response
        """)

    # Main chat interface
    st.markdown("## 💭 Ask a Question")

    query = st.chat_input("Query a sector dataset...")

    if query:
        # Display user message
        st.chat_message("user").write(query)
        headers = {"Authorization": f"Bearer {st.session_state['token']}"}

        with st.chat_message("assistant"):
            # Create containers for different streams
            thought_trace_container = st.container()
            response_container = st.container()

            # Containers for incremental rendering
            with thought_trace_container:
                st.markdown("### 🧠 Live Thought Trace")
                trace_expander = st.expander("Node Execution", expanded=True)

            with response_container:
                st.markdown("### 💬 Response")
                response_placeholder = st.empty()

            # Track nodes and response
            node_list = []
            accumulated_response = ""

            try:
                # Stream response with dual-stream SSE
                res = requests.post(
                    f"{API_URL}/chat/stream",
                    json={"query": query},
                    headers=headers,
                    stream=True,
                    timeout=120
                )

                if res.status_code == 200:
                    # Parse SSE stream
                    for line in res.iter_lines():
                        if not line:
                            continue

                        decoded_line = line.decode("utf-8")

                        if decoded_line.startswith("data: "):
                            try:
                                data_str = decoded_line.replace("data: ", "", 1)
                                event = json.loads(data_str)

                                event_type = event.get("type")
                                data = event.get("data", {})

                                # ================================================
                                # HANDLE UPDATE EVENTS (Node Trace)
                                # ================================================
                                if event_type == "update":
                                    node_name = data.get("node", "unknown")
                                    status = data.get("status", "executing")

                                    if status == "executing":
                                        node_list.append(node_name)
                                        with trace_expander:
                                            st.markdown(
                                                f'<div class="thought-trace">'
                                                f'<span class="node-executing">▶ {node_name}</span>'
                                                f'</div>',
                                                unsafe_allow_html=True
                                            )
                                        logger.info(f"Node: {node_name}")

                                    elif status == "completed":
                                        with trace_expander:
                                            st.markdown(
                                                f'<div class="thought-trace">'
                                                f'<span class="node-completed">✓ {node_name}</span>'
                                                f'</div>',
                                                unsafe_allow_html=True
                                            )

                                # ================================================
                                # HANDLE MESSAGE EVENTS (Token Stream)
                                # ================================================
                                elif event_type == "message":
                                    token = data.get("token", "")
                                    is_final = data.get("is_final", False)

                                    if token:
                                        accumulated_response += token

                                        # Incremental token rendering
                                        with response_placeholder.container():
                                            st.markdown(
                                                f'<div class="token-stream">'
                                                f'{accumulated_response}'
                                                f'</div>',
                                                unsafe_allow_html=True
                                            )

                                        logger.debug(f"Token: {token[:20]}...")

                                    if is_final:
                                        logger.info("Message stream completed")

                                # ================================================
                                # HANDLE ERROR EVENTS
                                # ================================================
                                elif event_type == "error":
                                    error_msg = data.get("message", "Unknown error")
                                    st.error(f"❌ Error: {error_msg}")

                                # ================================================
                                # HANDLE STATUS EVENTS
                                # ================================================
                                elif event_type == "status":
                                    status_msg = data.get("message", "")
                                    logger.info(f"Status: {status_msg}")

                            except json.JSONDecodeError:
                                logger.error(f"Failed to parse SSE event: {line[:100]}")
                                continue

                else:
                    st.error(f"❌ API Error: {res.status_code}")

            except requests.exceptions.Timeout:
                st.error("⏱️ Request timed out (120s)")
            except requests.exceptions.ConnectionError:
                st.error("🔌 Connection error: Backend may be offline")
            except Exception as e:
                st.error(f"❌ Unexpected error: {str(e)}")

            # Save to history
            st.divider()

            col1, col2 = st.columns([4, 1])

            with col1:
                if st.button("💾 Save to History"):
                    chat_entry = {
                        "query": query,
                        "response": accumulated_response,
                        "nodes": node_list
                    }
                    st.session_state.chat_history.append(chat_entry)
                    st.success("✅ Saved")

            with col2:
                if st.session_state.chat_history:
                    if st.button("📋 History"):
                        st.markdown("### Chat History")
                        for idx, entry in enumerate(st.session_state.chat_history, 1):
                            with st.expander(f"{idx}. {entry['query'][:50]}..."):
                                st.write(entry["response"])