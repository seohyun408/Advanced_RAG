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

export default function MessageBubble({ message, onRetry }) {
  const { role, text, route, error, pending, startedAt } = message;
  const cls = ["bubble", role, error ? "error" : ""].join(" ").trim();
  return (
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
  );
}
