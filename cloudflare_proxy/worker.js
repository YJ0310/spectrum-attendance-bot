/**
 * SPeCTRUM Reverse Proxy Cloudflare Worker
 *
 * Universiti Malaya SPeCTRUM blocks AWS/cloud datacenter IPs (like Render Singapore).
 * This Worker acts as a lightweight edge proxy between Render and spectrum.um.edu.my,
 * preserving all cookies (MoodleSession, cookiesession1) and rewriting redirects.
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "*",
        },
      });
    }

    // Target SPeCTRUM host
    const targetUrl = new URL(url.pathname + url.search, "https://spectrum.um.edu.my");

    const forwardHeaders = new Headers(request.headers);
    forwardHeaders.set("Host", "spectrum.um.edu.my");
    forwardHeaders.set("Origin", "https://spectrum.um.edu.my");

    // Rewrite Referer if present
    const referer = forwardHeaders.get("Referer");
    if (referer) {
      forwardHeaders.set("Referer", referer.replace(url.host, "spectrum.um.edu.my"));
    }

    const proxyRequest = new Request(targetUrl.toString(), {
      method: request.method,
      headers: forwardHeaders,
      body: request.method !== "GET" && request.method !== "HEAD" ? request.body : null,
      redirect: "manual", // Intercept redirects so we can rewrite Location back to proxy
    });

    try {
      const response = await fetch(proxyRequest);
      const responseHeaders = new Headers(response.headers);

      // Rewrite 301/302/303 Location headers so client stays on proxy
      const location = responseHeaders.get("Location");
      if (location) {
        responseHeaders.set("Location", location.replace("https://spectrum.um.edu.my", url.origin));
      }

      // Allow CORS for the Telegram Mini App
      responseHeaders.set("Access-Control-Allow-Origin", "*");
      responseHeaders.set("Access-Control-Allow-Credentials", "true");
      responseHeaders.set("Access-Control-Allow-Headers", "*");

      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      });
    } catch (err) {
      return new Response(`Proxy Error: ${err.message}`, { status: 502 });
    }
  },
};
