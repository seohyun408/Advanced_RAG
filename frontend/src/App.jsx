import { useCallback, useRef, useState } from "react";
import ChatWindow from "./components/ChatWindow.jsx";
import Composer from "./components/Composer.jsx";
import FaqBox from "./components/FaqBox.jsx";
import GlowBackground from "./components/GlowBackground.jsx";
import Sidebar from "./components/Sidebar.jsx";
import { useChat } from "./useChat.js";

export default function App() {
  const { messages, busy, ask, retry, clear } = useChat();
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);

  const showToast = useCallback((name) => {
    clearTimeout(toastTimer.current);
    setToast(`${name} 기능은 곧 출시 예정이에요 🚀`);
    toastTimer.current = setTimeout(() => setToast(null), 2200);
  }, []);

  return (
    <div className="app-shell">
      <GlowBackground />
      <div className="app">
        <header className="app-header">
          <div className="brand">
            <h1>RegiHelper</h1>
            <span className="brand-divider" />
            <span className="brand-sub">셀프 등기 어시스턴트</span>
          </div>
          <div className="header-right">
            {messages.length > 0 && (
              <button className="clear-btn" onClick={clear} disabled={busy}>
                대화 지우기
              </button>
            )}
          </div>
        </header>

        <div className="main-row">
          <main className="chat-col">
            {messages.length === 0 ? (
              <div className="welcome">
                <div className="hero">
                  <h2 className="hero-title">
                    등기, <span className="hero-accent">혼자서도</span> 할 수 있어요
                  </h2>
                  <p className="hero-sub">
                    소유권이전·말소·전자신청까지, 복잡한 등기 절차를 AI가 단계별로 안내해드립니다.
                  </p>
                </div>
                <FaqBox onPick={ask} disabled={busy} />
              </div>
            ) : (
              <ChatWindow messages={messages} onRetry={retry} />
            )}
            <Composer onSend={ask} disabled={busy} />
          </main>
          <Sidebar onToolClick={showToast} />
        </div>
      </div>
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
