import { ApiError } from "./api";

/**
 * Download an authenticated API response as a file, keeping errors visible to the caller.
 * The server's Content-Disposition filename wins (it names the business and period); `filename` is the fallback.
 */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const res = await fetch(`/api${path}`, { credentials: "same-origin" });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* not JSON */ }
    throw new ApiError(res.status, typeof detail === "string" ? detail : res.statusText);
  }
  const named = res.headers.get("content-disposition")?.match(/filename="?([^";]+)"?/)?.[1];
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = named ?? filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
