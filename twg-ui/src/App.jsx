import React, { useState, useRef, useEffect, useMemo } from 'react';
import { useSportsAgent } from './useSportsAgent';

function StatusPill({ isStreaming, hitlWaiting, hasError }) {
  let label = 'Idle';
  let className = 'status-pill status-idle';

  if (hasError) {
    label = 'Error';
    className = 'status-pill status-error';
  } else if (hitlWaiting) {
    label = 'Approval needed';
    className = 'status-pill status-waiting';
  } else if (isStreaming) {
    label = 'Streaming';
    className = 'status-pill status-streaming';
  }

  return (
    <div className={className}>
      <span className="status-dot" />
      <span>{label}</span>
    </div>
  );
}

function TracePanel({ activeTrace, isStreaming }) {
  if (!activeTrace.length && !isStreaming) return null;

  const completed = activeTrace.filter((t) => t.status === 'completed').length;
  const running = activeTrace.find((t) => t.status === 'running');
  const progress = activeTrace.length ? Math.round((completed / activeTrace.length) * 100) : 0;

  return (
    <section className="trace-card">
      <div className="trace-card-header">
        <div>
          <p className="eyebrow">Execution</p>
          <h3 className="trace-title">Node activity</h3>
        </div>
        <div className="trace-meta">
          <span>{completed}/{activeTrace.length} done</span>
          {running && <span className="trace-live">Running: {running.node}</span>}
        </div>
      </div>

      <div className="trace-progress">
        <div className="trace-progress-bar" style={{ width: `${progress}%` }} />
      </div>

      <div className="trace-list">
        {activeTrace.map((trace) => (
          <div key={trace.node} className="trace-row">
            <div className="trace-node-wrap">
              <span className={`trace-node-indicator trace-${trace.status}`} />
              <span className="trace-node-name">{trace.node}</span>
            </div>
            <span className={`trace-badge trace-badge-${trace.status}`}>
              {trace.status}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function MessageBubble({ msg, isLastAssistantMessage, isStreaming }) {
  const isUser = msg.role === 'user';
  const showStreamingCursor =
    !isUser && isLastAssistantMessage && isStreaming && msg.content?.length > 0;

  return (
    <div className={`message-row ${isUser ? 'message-row-user' : 'message-row-ai'}`}>
      <div className={`message-bubble ${isUser ? 'message-user' : 'message-ai'}`}>
        <div className="message-label">
          {isUser ? 'You' : 'Agent'}
        </div>

        {!isUser && !msg.content && isStreaming ? (
          <div className="typing-shell">
            <span className="typing-dot" />
            <span className="typing-dot" />
            <span className="typing-dot" />
            <span className="typing-text">Thinking…</span>
          </div>
        ) : (
          <div className="message-content">
            {msg.content}
            {showStreamingCursor && <span className="streaming-cursor" />}
          </div>
        )}
      </div>
    </div>
  );
}

function ApprovalCard({ hitlState, resumeGraph }) {
  if (!hitlState.isWaiting) return null;

  return (
    <section className="approval-card">
      <div className="approval-header">
        <div className="approval-icon">!</div>
        <div>
          <p className="eyebrow">Human in the loop</p>
          <h3 className="approval-title">Approval required before execution</h3>
        </div>
      </div>

      <div className="approval-body">
        {hitlState.data?.message ||
          'The agent is about to execute a sensitive, destructive, or high-cost action.'}
      </div>

      <div className="approval-actions">
        <button
          onClick={() => resumeGraph(true)}
          className="primary-btn"
        >
          Approve
        </button>
        <button
          onClick={() => resumeGraph(false)}
          className="secondary-btn"
        >
          Reject
        </button>
      </div>
    </section>
  );
}

export default function App() {
  const [input, setInput] = useState('');
  const {
    messages,
    activeTrace,
    isStreaming,
    hitlState,
    streamChat,
    resumeGraph,
    error,
  } = useSportsAgent();

  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, activeTrace, hitlState]);

  const handleSend = (e) => {
    e.preventDefault();
    if (!input.trim() || isStreaming || hitlState.isWaiting) return;
    streamChat(input.trim());
    setInput('');
  };

  const lastAssistantIndex = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].role === 'ai') return i;
    }
    return -1;
  }, [messages]);

  return (
    <div className="app-shell">
      <div className="app-frame">
        <header className="topbar">
          <div>
            <p className="eyebrow">Sports intelligence console</p>
            <h1 className="app-title">TWG Sports Intelligence</h1>
          </div>

          <StatusPill
            isStreaming={isStreaming}
            hitlWaiting={hitlState.isWaiting}
            hasError={Boolean(error)}
          />
        </header>

        <main className="main-grid">
          <section className="chat-panel">
            <div className="chat-scroll">
              {messages.length === 0 && (
                <div className="empty-state">
                  <div className="empty-orb" />
                  <h2>Ask a sports question</h2>
                  <p>
                    Responses will stream live, node execution will update in real time,
                    and sensitive actions can pause for approval.
                  </p>
                </div>
              )}

              {messages.map((msg, idx) => (
                <MessageBubble
                  key={idx}
                  msg={msg}
                  isLastAssistantMessage={idx === lastAssistantIndex}
                  isStreaming={isStreaming}
                />
              ))}

              {error && (
                <div className="error-banner">
                  {error}
                </div>
              )}

              <ApprovalCard hitlState={hitlState} resumeGraph={resumeGraph} />
              <div ref={messagesEndRef} />
            </div>

            <form onSubmit={handleSend} className="composer">
              <div className="composer-inner">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  disabled={isStreaming || hitlState.isWaiting}
                  placeholder={
                    hitlState.isWaiting
                      ? 'Waiting for approval…'
                      : "Ask something like: Who had the fastest lap in the last race?"
                  }
                  className="composer-input"
                />
                <button
                  type="submit"
                  disabled={!input.trim() || isStreaming || hitlState.isWaiting}
                  className="composer-button"
                >
                  Send
                </button>
              </div>
            </form>
          </section>

          <aside className="side-panel">
            <TracePanel activeTrace={activeTrace} isStreaming={isStreaming} />

            <section className="info-card">
              <p className="eyebrow">Why this feels faster</p>
              <ul className="info-list">
                <li>Immediate assistant placeholder before first token</li>
                <li>Live token streaming with cursor feedback</li>
                <li>Node progress visible while answer is being formed</li>
                <li>Approval checkpoint separated from normal messaging flow</li>
              </ul>
            </section>
          </aside>
        </main>
      </div>
    </div>
  );
}