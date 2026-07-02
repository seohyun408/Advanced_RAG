import { useState } from "react";

export default function Composer({ onSend, disabled }) {
  const [text, setText] = useState("");

  const submit = (e) => {
    e.preventDefault();
    if (disabled || !text.trim()) return;
    onSend(text);
    setText("");
  };

  return (
    <form className="composer" onSubmit={submit}>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={disabled ? "답변을 기다리는 중..." : "등기 관련 질문을 입력하세요"}
        disabled={disabled}
      />
      <button className="send-btn" type="submit" disabled={disabled || !text.trim()}>
        전송
      </button>
    </form>
  );
}
