import type {
  ChatMessage,
  ChatResponse,
  ReportDetail,
  ReportSummary,
  SuggestedQuestions,
  UploadResponse,
} from "@/types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "/api/backend";

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function uploadReport(
  file: File,
  onProgress?: (pct: number) => void,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);

  // Use XHR so we can report upload progress (fetch cannot)
  return new Promise<UploadResponse>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/upload`, true);
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable && onProgress) {
        onProgress(Math.round((ev.loaded / ev.total) * 100));
      }
    };
    xhr.onerror = () => reject(new Error("Upload failed — network error"));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch (e) {
          reject(e);
        }
      } else {
        let msg = xhr.statusText;
        try {
          msg = JSON.parse(xhr.responseText).detail ?? msg;
        } catch {
          /* ignore */
        }
        reject(new Error(`${xhr.status}: ${msg}`));
      }
    };
    xhr.send(form);
  });
}

export async function getReport(id: string): Promise<ReportDetail> {
  const res = await fetch(`${API_BASE}/report/${id}`, { cache: "no-store" });
  return handle<ReportDetail>(res);
}

export async function getSuggestedQuestions(id: string): Promise<SuggestedQuestions> {
  const res = await fetch(`${API_BASE}/report/${id}/questions`, { cache: "no-store" });
  return handle<SuggestedQuestions>(res);
}

export async function getSummary(id: string): Promise<ReportSummary> {
  const res = await fetch(`${API_BASE}/report/${id}/summary`, { cache: "no-store" });
  return handle<ReportSummary>(res);
}

export async function postChatMessage(id: string, message: string): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/chat/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return handle<ChatResponse>(res);
}

export async function getChatHistory(id: string): Promise<ChatMessage[]> {
  const res = await fetch(`${API_BASE}/chat/${id}/history`, { cache: "no-store" });
  return handle<ChatMessage[]>(res);
}

export async function deleteReport(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/report/${id}`, { method: "DELETE" });
  await handle<{ deleted: boolean }>(res);
}
