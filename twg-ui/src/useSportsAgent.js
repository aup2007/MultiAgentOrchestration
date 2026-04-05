import { useMemo, useState } from 'react';

export function useSportsAgent() {
  const [messages, setMessages] = useState([]);
  const [traceMap, setTraceMap] = useState({});
  const [traceOrder, setTraceOrder] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [hitlState, setHitlState] = useState({ isWaiting: false, data: null });
  const [error, setError] = useState('');

  const activeTrace = useMemo(() => {
    return traceOrder.map((node) => traceMap[node]).filter(Boolean);
  }, [traceMap, traceOrder]);

  const upsertTraceNode = (node, status) => {
    setTraceMap((prev) => ({
      ...prev,
      [node]: { node, status },
    }));

    setTraceOrder((prev) => {
      if (prev.includes(node)) return prev;
      return [...prev, node];
    });
  };

  const appendAssistantToken = (token) => {
    setMessages((prev) => {
      const next = [...prev];
      const lastIndex = next.length - 1;

      if (lastIndex >= 0 && next[lastIndex].role === 'ai') {
        next[lastIndex] = {
          ...next[lastIndex],
          content: `${next[lastIndex].content}${token}`,
        };
      }

      return next;
    });
  };

  const updateAssistantMessage = (content) => {
    setMessages((prev) => {
      const next = [...prev];
      const lastIndex = next.length - 1;

      if (lastIndex >= 0 && next[lastIndex].role === 'ai') {
        next[lastIndex] = {
          ...next[lastIndex],
          content,
        };
      }

      return next;
    });
  };

  const streamChat = async (query) => {
    setError('');
    setIsStreaming(true);
    setHitlState({ isWaiting: false, data: null });
    setTraceMap({});
    setTraceOrder([]);

    setMessages((prev) => [
      ...prev,
      { role: 'user', content: query },
      { role: 'ai', content: '' },
    ]);

    try {
      const response = await fetch('http://localhost:8000/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, user_role: 'admin' }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`Streaming request failed with status ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() || '';

        for (const rawEvent of events) {
          const trimmed = rawEvent.trim();
          if (!trimmed.startsWith('data: ')) continue;

          let event;
          try {
            event = JSON.parse(trimmed.slice(6));
          } catch (parseErr) {
            console.error('Failed to parse SSE event:', parseErr, trimmed);
            continue;
          }

          if (event.type === 'update') {
            const node = event.data?.node || 'unknown-node';
            const status = event.data?.status || 'running';
            upsertTraceNode(node, status);
          } else if (event.type === 'message') {
            if (typeof event.data?.token === 'string') {
              appendAssistantToken(event.data.token);
            }

            if (typeof event.data?.content === 'string') {
              updateAssistantMessage(event.data.content);
            }
          } else if (event.type === 'interrupt') {
            setHitlState({ isWaiting: true, data: event.data || null });
            setIsStreaming(false);
            return;
          } else if (event.type === 'error') {
            throw new Error(event.data?.message || 'Unknown streaming error');
          } else if (event.type === 'done') {
            setIsStreaming(false);
          }
        }
      }
    } catch (err) {
      console.error('Stream failed:', err);
      setError(err.message || 'Something went wrong while streaming the response.');

      setMessages((prev) => {
        const next = [...prev];
        const lastIndex = next.length - 1;

        if (lastIndex >= 0 && next[lastIndex].role === 'ai' && !next[lastIndex].content) {
          next[lastIndex] = {
            ...next[lastIndex],
            content: 'Something went wrong while generating the response.',
          };
        }

        return next;
      });
    } finally {
      setIsStreaming(false);
    }
  };

  const resumeGraph = async (approved) => {
    setError('');
    setHitlState({ isWaiting: false, data: null });

    if (!approved) {
      setMessages((prev) => {
        const next = [...prev];
        const lastIndex = next.length - 1;

        if (lastIndex >= 0 && next[lastIndex].role === 'ai') {
          next[lastIndex] = {
            ...next[lastIndex],
            content: `${next[lastIndex].content}\n\n[Execution cancelled by user]`,
          };
        }

        return next;
      });
      return;
    }

    setIsStreaming(true);

    try {
      const res = await fetch('http://localhost:8000/chat/resume', {
        method: 'POST',
      });

      if (!res.ok) {
        throw new Error(`Resume failed with status ${res.status}`);
      }

      const data = await res.json();

      if (data?.final_response) {
        updateAssistantMessage(data.final_response);
      } else {
        updateAssistantMessage('Execution resumed, but no final response was returned.');
      }
    } catch (err) {
      console.error('Resume failed:', err);
      setError(err.message || 'Failed to resume execution.');
      updateAssistantMessage('Failed to resume execution.');
    } finally {
      setIsStreaming(false);
    }
  };

  return {
    messages,
    activeTrace,
    isStreaming,
    hitlState,
    streamChat,
    resumeGraph,
    error,
  };
}