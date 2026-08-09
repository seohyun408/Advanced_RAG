const TOOLS = [
  {
    icon: "📋",
    name: "서류 체크리스트",
    desc: "등기 유형별 필요서류 자동 점검",
  },
  {
    icon: "🧮",
    name: "등기비용 계산기",
    desc: "취득세·수수료·채권 비용 계산",
  },
  {
    icon: "📄",
    name: "문서 분석",
    desc: "등기부등본 업로드 시 AI 해석",
  },
  {
    icon: "🗺️",
    name: "진행상황 트래커",
    desc: "내 등기 단계별 진행 현황",
  },
];

const STEPS = ["서류 준비", "신청서 작성", "세금 납부", "등기소 제출", "완료"];

export default function Sidebar({ onToolClick }) {
  return (
    <aside className="sidebar">
      <section className="side-panel">
        <div className="side-panel-title">
          도구 <span className="soon-pill">준비중</span>
        </div>
        <div className="tool-list">
          {TOOLS.map((t, i) => (
            <button
              key={t.name}
              className="tool-card"
              style={{ animationDelay: `${i * 80}ms` }}
              onClick={() => onToolClick(t.name)}
            >
              <span className="tool-icon">{t.icon}</span>
              <span className="tool-text">
                <span className="tool-name">{t.name}</span>
                <span className="tool-desc">{t.desc}</span>
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="side-panel">
        <div className="side-panel-title">
          셀프 등기 로드맵 <span className="soon-pill">준비중</span>
        </div>
        <ol className="roadmap">
          {STEPS.map((s, i) => (
            <li key={s} className={`roadmap-step ${i === 0 ? "current" : ""}`}>
              <span className="roadmap-dot" />
              {s}
            </li>
          ))}
        </ol>
      </section>
    </aside>
  );
}
