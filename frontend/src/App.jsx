import ChatWindow from "./components/ChatWindow.jsx";
import Composer from "./components/Composer.jsx";
import ExampleQuestions from "./components/ExampleQuestions.jsx";
import { useChat } from "./useChat.js";

export default function App() {
  const { messages, busy, ask, retry, clear } = useChat();

  return (
    <div className="app">
      <header className="app-header">
        <h1>부동산 등기 어시스턴트</h1>
        {messages.length > 0 && (
          <button className="clear-btn" onClick={clear} disabled={busy}>
            대화 지우기
          </button>
        )}
      </header>
      {messages.length === 0 ? (
        <ExampleQuestions onPick={ask} disabled={busy} />
      ) : (
        <ChatWindow messages={messages} onRetry={retry} />
      )}
      <Composer onSend={ask} disabled={busy} />
    </div>
  );
}
