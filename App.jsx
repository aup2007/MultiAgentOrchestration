import React, { useState, useRef, useEffect } from 'react';

const API_URL = "http://localhost:8000";

export default function App() {
  const [token, setToken] = useState(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  // Chat State
  const [chatHistory, setChatHistory] = useState([]);
  const [currentQuery, setCurrentQuery] = useState("");
  const [inputQuery, setInputQuery] = useState("");
  
  // Streaming State
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentResponse, setCurrentResponse] = useState("");
  const [activeNodes, setActiveNodes] = useState([]);
  const [awaitingApproval, setAwaitingApproval] = useState(false);
  const [currentThreadId, setCurrentThreadId] = useState(null);

  const messagesEndRef = useRef(null);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [currentResponse, chatHistory]);

  const handleLogin = async (e) => {
    e.preventDefault();
    const formData = new URLSearchParams();
    formData.append("username", username);
    formData.append("password", password);

    try {
      const res = await fetch(`${API_URL}/token`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: formData,
      });
      if (res.ok) {
        const data = await res.json();
        setToken(data.access_token);
      } else {
        alert("Authentication Failed");
      }
    } catch (err) {
      console.error(err);
      alert("Network Error");
    }
  };

  const handleSendMessage = async (e) => {
    e.preventDefault();
    if (!inputQuery.trim() || awaitingApproval) return;

    const query = inputQuery;
    setCurrentQuery(query);
    setInputQuery("");
    setCurrentResponse("");
    setActiveNodes([]);
    setIsStreaming(true);
    setAwaitingApproval(false);

    try {

      // POST requests with SSE require the native fetch API and a ReadableStream reader
      const newThreadId = crypto.randomUUID();
      setCurrentThreadId(newThreadId);
      const res = await fetch(`${API_URL}/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ query: query,
          user_role: "user",
          thread_id: newThreadId })
      });

      if (!res.ok) throw new Error("API Error");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let done = false;
      let textAccumulator = "";

      while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;
        if (value) {
          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split('\n\n');
          
          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const event = JSON.parse(line.replace("data: ", ""));
                
                // 1. Handle Node Execution Trace
                if (event.type === "update") {
                  const nodeName = event.data.node;
                  const status = event.data.status;
                  setActiveNodes(prev => {
                    const exists = prev.find(n => n.name === nodeName);
                    if (exists) {
                      return prev.map(n => n.name === nodeName ? { ...n, status } : n);
                    }
                    return [...prev, { name: nodeName, status }];
                  });
                }
                
                // 2. Handle Token Streaming
                else if (event.type === "message") {
                  if (event.data.token) {
                    textAccumulator += event.data.token;
                    setCurrentResponse(textAccumulator);
                  }
                }
                
                // 3. Handle Human-in-the-Loop Pause
                else if (event.type === "interrupt") {
                  setAwaitingApproval(true);
                  setIsStreaming(false);
                }
              } catch (e) {
                console.error("Failed to parse SSE event", e);
              }
            }
          }
        }
      }
      
      if (!awaitingApproval) {
          setIsStreaming(false);
          setChatHistory(prev => [...prev, { query, response: textAccumulator }]);
          setCurrentResponse("");
          setActiveNodes([]);
      }

    } catch (err) {
      console.error(err);
      setIsStreaming(false);
      alert("Error communicating with backend.");
    }
  };

  const handleApprove = async () => {
    setAwaitingApproval(false);
    setIsStreaming(true);
    setActiveNodes(prev => [...prev, { name: "Executing API...", status: "executing" }]);

    try {
      const res = await fetch(`${API_URL}/chat/resume`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` },
        body: JSON.stringify({
          thread_id: currentThreadId,
          action: "approved"
        })
      });
      
      if (res.ok) {
        const data = await res.json();
        setChatHistory(prev => [...prev, { query: currentQuery, response: data.final_response }]);
        setCurrentResponse("");
        setActiveNodes([]);
      }
    } catch (err) {
      console.error(err);
      alert("Error resuming graph.");
    }
    setIsStreaming(false);
  };

  const handleCancel = () => {
    setAwaitingApproval(false);
    setCurrentResponse("");
    setActiveNodes([]);
    setIsStreaming(false);
  };

  // --- RENDER LOGIN ---
  if (!token) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-100">
        <div className="bg-white p-8 rounded shadow-md w-96">
          <h1 className="text-2xl font-bold mb-6 text-center">TWG Global</h1>
          <form onSubmit={handleLogin} className="space-y-4">
            <input
              type="text"
              placeholder="Username"
              className="w-full border p-2 rounded"
              value={username}
              onChange={e => setUsername(e.target.value)}
            />
            <input
              type="password"
              placeholder="Password"
              className="w-full border p-2 rounded"
              value={password}
              onChange={e => setPassword(e.target.value)}
            />
            <button type="submit" className="w-full bg-blue-600 text-white p-2 rounded hover:bg-blue-700">
              Authenticate
            </button>
          </form>
        </div>
      </div>
    );
  }

  // --- RENDER CHAT INTERFACE ---
  return (
    <div className="flex flex-col h-screen bg-gray-50 font-sans">
      <header className="bg-white shadow p-4 flex justify-between items-center">
        <h1 className="text-xl font-bold text-gray-800">🏆 TWG Sports Intelligence</h1>
        <button onClick={() => setToken(null)} className="text-sm text-gray-500 hover:text-red-500">
          Logout
        </button>
      </header>

      <main className="flex-1 overflow-y-auto p-4 md:px-24 lg:px-64 space-y-6">
        {/* Chat History */}
        {chatHistory.map((msg, idx) => (
          <div key={idx} className="space-y-4">
            <div className="flex justify-end">
              <div className="bg-blue-600 text-white p-3 rounded-xl max-w-lg">{msg.query}</div>
            </div>
            <div className="flex justify-start">
              <div className="bg-white border p-4 rounded-xl max-w-2xl text-gray-800 whitespace-pre-wrap">
                {msg.response}
              </div>
            </div>
          </div>
        ))}

        {/* Active Stream */}
        {(isStreaming || awaitingApproval) && (
          <div className="space-y-4">
            <div className="flex justify-end">
              <div className="bg-blue-600 text-white p-3 rounded-xl max-w-lg">{currentQuery}</div>
            </div>
            
            <div className="flex justify-start flex-col gap-2">
              {/* Thought Trace Dropdown */}
              {activeNodes.length > 0 && (
                <div className="bg-gray-100 p-3 rounded-lg text-sm font-mono text-gray-600 w-fit">
                  <span className="font-bold text-blue-500">🧠 Agent Trace:</span>
                  <ul className="mt-2 space-y-1">
                    {activeNodes.map((n, i) => (
                      <li key={i} className={n.status === 'completed' ? 'text-green-600' : 'text-orange-500 animate-pulse'}>
                        {n.status === 'completed' ? '✓' : '▶'} {n.name}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Streaming Text */}
              {currentResponse && (
                <div className="bg-white border p-4 rounded-xl max-w-2xl text-gray-800 whitespace-pre-wrap">
                  {currentResponse} <span className="animate-pulse">▌</span>
                </div>
              )}

              {/* Human-in-the-Loop Interceptor */}
              {awaitingApproval && (
                <div className="bg-yellow-50 border-l-4 border-yellow-400 p-4 rounded mt-4 max-w-xl">
                  <h3 className="font-bold text-yellow-800 flex items-center gap-2">
                    🚨 Action Required
                  </h3>
                  <p className="text-yellow-700 mt-1">The Agent is requesting permission to execute an external API call.</p>
                  <div className="flex gap-3 mt-4">
                    <button onClick={handleApprove} className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded font-medium shadow-sm transition-colors">
                      ✅ Approve Execution
                    </button>
                    <button onClick={handleCancel} className="bg-red-100 hover:bg-red-200 text-red-700 px-4 py-2 rounded font-medium transition-colors">
                      ❌ Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </main>

      {/* Input Bar */}
      <footer className="bg-white border-t p-4">
        <form onSubmit={handleSendMessage} className="max-w-4xl mx-auto flex gap-2">
          <input
            type="text"
            disabled={isStreaming || awaitingApproval}
            className="flex-1 border border-gray-300 rounded-full px-6 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
            placeholder={awaitingApproval ? "Please approve or cancel the action above..." : "Ask about Chelsea, F1, or Baseball..."}
            value={inputQuery}
            onChange={e => setInputQuery(e.target.value)}
          />
          <button 
            type="submit" 
            disabled={!inputQuery.trim() || isStreaming || awaitingApproval}
            className="bg-blue-600 text-white px-6 rounded-full font-medium hover:bg-blue-700 disabled:opacity-50 transition-opacity"
          >
            Send
          </button>
        </form>
      </footer>
    </div>
  );
}