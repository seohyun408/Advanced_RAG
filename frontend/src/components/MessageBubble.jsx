import { useEffect, useState } from "react";

function Typing({ startedAt }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(t);
  }, [startedAt]);
  return (
    <span className="typing">
      <span /><span /><span />
      <em className="elapsed">{elapsed}초</em>
    </span>
  );
}

function formatTime(ts) {
  return new Date(ts).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

export default function MessageBubble({ message, onRetry }) {
  const { role, text, route, error, pending, startedAt, ts } = message;
  const cls = ["bubble", role, error ? "error" : ""].join(" ").trim();
  return (
    <div className={`bubble-wrap ${role}`}>
      <div className={cls}>
        {pending ? (
          <Typing startedAt={startedAt ?? Date.now()} />
        ) : error ? (
          <>
            <div className="error-text">{error}</div>
            {onRetry && (
              <button className="retry-btn" onClick={onRetry}>다시 시도</button>
            )}
          </>
        ) : (
          <>
            {text}
            {route && <div className="route-badge">경로: {route.join(" · ")}</div>}
          </>
        )}
      </div>
      {!pending && ts && <div className="msg-time">{formatTime(ts)}</div>}
    </div>
  );
}
