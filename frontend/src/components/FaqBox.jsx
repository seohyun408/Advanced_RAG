import { useState } from "react";

const CATEGORIES = [
  {
    id: "transfer",
    label: "소유권이전",
    questions: [
      "소유권이전등기에 필요한 서류는 무엇인가요?",
      "잔금일에 매도인에게 받아야 할 서류는 무엇인가요?",
      "취득세 신고와 납부는 어떻게 하나요?",
      "소유권이전등기 신청서 작성 방법을 알려주세요",
    ],
  },
  {
    id: "cancel",
    label: "말소등기",
    questions: [
      "근저당권 말소 절차를 알려주세요",
      "근저당권 말소에 필요한 서류는 무엇인가요?",
      "말소등기 등록면허세는 얼마인가요?",
    ],
  },
  {
    id: "eform",
    label: "전자신청",
    questions: [
      "전자신청 사용자등록은 어떻게 하나요?",
      "인터넷등기소 전자신청 절차를 알려주세요",
      "전자신청 시 공동인증서는 어떻게 준비하나요?",
    ],
  },
  {
    id: "docs",
    label: "서류작성",
    questions: [
      "은행에 보낼 서류 요청 이메일을 작성해주세요",
      "위임장은 어떻게 작성하나요?",
      "등기신청 수수료는 어떻게 납부하나요?",
    ],
  },
];

export default function FaqBox({ onPick, disabled }) {
  const [active, setActive] = useState(CATEGORIES[0].id);
  const current = CATEGORIES.find((c) => c.id === active);

  return (
    <div className="faq-box">
      <div className="faq-title">
        <span className="faq-title-icon">💬</span> 자주 묻는 질문
      </div>
      <div className="faq-tabs" role="tablist">
        {CATEGORIES.map((c) => (
          <button
            key={c.id}
            role="tab"
            aria-selected={c.id === active}
            className={`faq-tab ${c.id === active ? "active" : ""}`}
            onClick={() => setActive(c.id)}
          >
            {c.label}
          </button>
        ))}
      </div>
      <div className="faq-list" key={active}>
        {current.questions.map((q, i) => (
          <button
            key={q}
            className="faq-item"
            style={{ animationDelay: `${i * 60}ms` }}
            onClick={() => onPick(q)}
            disabled={disabled}
          >
            <span className="faq-item-arrow">▸</span>
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
