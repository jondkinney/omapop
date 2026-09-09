// Shared fetch, XHR and Axios limits apply even when callers omit a timeout.
// Native networking remains possible with runtime network permission; this
// compatibility layer is not a proxy that contains hostile extension code.
export const HTTP_MAX_BYTES = 1024 * 1024;
export const HTTP_TIMEOUT_MS = 20000;
export const HTTP_MAX_REQUEST_BYTES = 256 * 1024;

export function checkHttpUrl(value) {
  const url = new URL(String(value));
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (url.username || url.password || (url.protocol !== "https:" && !(url.protocol === "http:" && loopback)))
    throw new Error("HTTP requests require HTTPS (HTTP is allowed only on loopback)");
  return url;
}

export function limitedFetch(transport, permitted, { maxBytes = HTTP_MAX_BYTES, timeoutMs = HTTP_TIMEOUT_MS } = {}) {
  let active = 0;
  return async function fetchBounded(input, init = {}) {
    if (!permitted()) throw new Error("network access is unavailable for this extension/action");
    if (active >= 4) throw new Error("at most four concurrent HTTP requests are allowed");
    if (input instanceof Request) throw new Error("use a URL and request options for bounded HTTP");
    let url = checkHttpUrl(input);
    let body = init.body;
    if (body instanceof URLSearchParams) body = body.toString();
    const size = typeof body === "string" ? new TextEncoder().encode(body).length
      : body instanceof Uint8Array ? body.byteLength : body == null ? 0 : Infinity;
    if (size > HTTP_MAX_REQUEST_BYTES) throw new Error("HTTP request body exceeds limit");
    const redirectMode = init.redirect || 'follow';
    if (!['follow', 'manual', 'error'].includes(redirectMode)) throw new Error('Invalid HTTP redirect mode');
    const controller = new AbortController();
    const abort = () => controller.abort(init.signal?.reason);
    if (init.signal?.aborted) abort();
    init.signal?.addEventListener("abort", abort, { once: true });
    const timer = setTimeout(() => controller.abort(new Error("HTTP request exceeded its total deadline")), timeoutMs);
    active++;
    let response;
    try {
      let method = String(init.method || "GET").toUpperCase();
      let headers = new Headers(init.headers);
      for (let redirects = 0; ; redirects++) {
        response = await transport(url.href, { method, headers, body, signal: controller.signal, redirect: "manual", credentials: init.credentials || 'omit' });
        if (![301, 302, 303, 307, 308].includes(response.status)) break;
        if (redirectMode === 'manual') break;
        if (redirectMode === 'error') throw new Error('HTTP redirect is forbidden for this request');
        const location = response.headers.get("location");
        await response.body?.cancel();
        if (!location || redirects >= 5) throw new Error("HTTP redirect limit exceeded");
        const next = checkHttpUrl(new URL(location, url));
        if (next.origin !== url.origin) {
          // No application credentials are forwarded to a different origin.
          throw new Error("HTTP redirects across origins require a separate request");
        }
        if (response.status === 303 || ([301, 302].includes(response.status) && method === "POST")) {
          method = "GET"; body = undefined;
          headers.delete("content-type"); headers.delete("content-length");
        }
        url = next;
      }
      const length = response.headers.get("content-length");
      if (length !== null && (!/^\d+$/.test(length) || Number(length) > maxBytes))
        throw new Error("HTTP response exceeds byte limit");
      const reader = response.body?.getReader();
      const chunks = [];
      let total = 0;
      if (reader) {
        try {
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            total += value.byteLength;
            if (total > maxBytes) throw new Error("HTTP response exceeds byte limit");
            chunks.push(value);
          }
        } catch (error) {
          controller.abort(error);
          await reader.cancel().catch(() => {});
          throw error;
        } finally { reader.releaseLock(); }
      }
      const bytes = new Uint8Array(total);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
      return new Response([101, 204, 205, 304].includes(response.status) ? null : bytes,
        { status: response.status, statusText: response.statusText, headers: response.headers });
    } catch (error) {
      controller.abort(error);
      await response?.body?.cancel().catch(() => {});
      throw error;
    } finally {
      clearTimeout(timer);
      init.signal?.removeEventListener("abort", abort);
      active--;
    }
  };
}
