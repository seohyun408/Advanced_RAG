const EXAMPLES = [
  "소유권이전등기에 필요한 서류는 무엇인가요?",
  "전자신청 사용자등록은 어떻게 하나요?",
  "근저당권 말소 절차를 알려주세요",
  "은행에 보낼 서류 요청 이메일을 작성해주세요",
];

export default function ExampleQuestions({ onPick, disabled }) {
  return (
    <div className="examples">
      {EXAMPLES.map((q) => (
        <button key={q} className="example-card" onClick={() => onPick(q)} disabled={disabled}>
          {q}
        </button>
      ))}
    </div>
  );
}
