/** JSON requests with a bounded wait and user-facing errors. */
export async function requestJson<T>(url: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const cancel = () => controller.abort();
  init.signal?.addEventListener("abort", cancel, { once: true });
  if (init.signal?.aborted) cancel();
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, 15_000);

  try {
    const headers = new Headers(init.headers);
    if (!headers.has("Accept")) headers.set("Accept", "application/json");
    const response = await fetch(url, {
      cache: "no-store",
      ...init,
      signal: controller.signal,
      headers,
    });
    if (response.status === 204) return null as T;
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      const message = typeof body?.error === "string" ? body.error : null;
      throw new Error(message ?? `The request failed (${response.status}). Please try again.`);
    }
    if (body === null) throw new Error("The service returned an unexpected response. Please try again.");
    return body as T;
  } catch (error) {
    if (init.signal?.aborted) throw error;
    if (timedOut) throw new Error("The request took too long. Please try again.");
    if (error instanceof TypeError) throw new Error("Could not connect to the service. Please try again.");
    throw error;
  } finally {
    clearTimeout(timeout);
    init.signal?.removeEventListener("abort", cancel);
  }
}
