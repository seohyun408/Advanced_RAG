import { useEffect, useRef } from "react";

// 커서를 따라다니는 빛번짐 + 떠다니는 오로라 블롭.
// rAF로 스로틀해서 mousemove마다 스타일을 직접 쓰지 않는다.
export default function GlowBackground() {
  const glowRef = useRef(null);

  useEffect(() => {
    let raf = 0;
    let x = window.innerWidth / 2;
    let y = window.innerHeight / 3;

    const onMove = (e) => {
      x = e.clientX;
      y = e.clientY;
      if (!raf) {
        raf = requestAnimationFrame(() => {
          raf = 0;
          glowRef.current?.style.setProperty("--mx", `${x}px`);
          glowRef.current?.style.setProperty("--my", `${y}px`);
        });
      }
    };

    window.addEventListener("mousemove", onMove);
    return () => {
      window.removeEventListener("mousemove", onMove);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div className="glow-bg" aria-hidden="true">
      <div className="cursor-glow" ref={glowRef} />
      <div className="aurora aurora-1" />
      <div className="aurora aurora-2" />
      <div className="aurora aurora-3" />
      <div className="grid-overlay" />
    </div>
  );
}
