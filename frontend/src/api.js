const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function submitJob(userInput) {
  const res = await fetch(`${API_URL}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_input: userInput }),
  });
  if (!res.ok) throw new Error(`요청 실패 (HTTP ${res.status})`);
  return res.json();
}

export async function getJob(jobId) {
  const res = await fetch(`${API_URL}/jobs/${jobId}`);
  if (!res.ok) throw new Error(`상태 조회 실패 (HTTP ${res.status})`);
  return res.json();
}
