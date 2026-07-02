import { useEffect, useRef } from "react";
import MessageBubble from "./MessageBubble.jsx";

export default function ChatWindow({ messages, onRetry }) {
  const endRef = useRef(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="chat-window">
      {messages.map((m, i) => (
        <MessageBubble
          key={m.id}
          message={m}
          onRetry={m.error && i === messages.length - 1 ? onRetry : undefined}
        />
      ))}
      <div ref={endRef} />
    </div>
  );
}
