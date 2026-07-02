import { useCallback, useEffect, useRef, useState } from "react";
import { getJob, submitJob } from "./api.js";

const STORAGE_KEY = "registry-chat-v1";
const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 90000;

function loadMessages() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) ?? [];
  } catch {
    return [];
  }
}

export function useChat() {
  const [messages, setMessages] = useState(loadMessages);
  const [busy, setBusy] = useState(false);
  const lastQuestionRef = useRef(null);

  useEffect(() => {
    // pending 상태는 저장하지 않고 완료된 대화만 보존
    const done = messages.filter((m) => !m.pending);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(done));
  }, [messages]);

  const ask = useCallback(async (text) => {
    const question = text.trim();
    if (!question) return;
    lastQuestionRef.current = question;
    setBusy(true);

    const userMsg = { id: crypto.randomUUID(), role: "user", text: question, ts: Date.now() };
    const pendingId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: pendingId, role: "assistant", text: "", pending: true, startedAt: Date.now() },
    ]);

    const finish = (patch) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingId ? { ...m, pending: false, ts: Date.now(), ...patch } : m
        )
      );
      setBusy(false);
    };

    try {
      const { job_id } = await submitJob(question);
      const deadline = Date.now() + POLL_TIMEOUT_MS;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
        const job = await getJob(job_id);
        if (job.status === "done") {
          finish({ text: job.output, route: job.route });
          return;
        }
        if (job.status === "error") {
          finish({ text: "", error: `처리 중 오류가 발생했습니다: ${job.error}` });
          return;
        }
      }
      finish({ text: "", error: "응답이 지연되고 있습니다. 다시 시도해주세요." });
    } catch (e) {
      finish({ text: "", error: e.message || "네트워크 오류가 발생했습니다." });
    }
  }, []);

  const retry = useCallback(() => {
    if (lastQuestionRef.current && !busy) {
      // 실패한 말풍선 쌍을 제거하고 재제출
      setMessages((prev) => prev.slice(0, -2));
      ask(lastQuestionRef.current);
    }
  }, [ask, busy]);

  const clear = useCallback(() => {
    setMessages([]);
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  return { messages, busy, ask, retry, clear };
}
