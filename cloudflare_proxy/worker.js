/**
 * SPeCTRUM Reverse Proxy & 1-Tap SSO Sync Cloudflare Worker
 *
 * 1. Bypasses UM campus firewall block on cloud datacenter IPs (like Render Singapore).
 * 2. Provides 1-Tap SSO login (/auth/connect) with automatic MoodleSession cookie capture.
 * 3. Automatically syncs captured session to Render backend and auto-closes the window.
 */

const RENDER_LOGIN_API = "https://spectrum-attendance-bot.onrender.com/api/login";

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

    // 1-Tap SSO Gateway: /auth/connect initiates Microsoft SSO via SPeCTRUM
    if (url.pathname === "/auth/connect") {
      const loginUrl = new URL("/login/index.php", url.origin);
      loginUrl.searchParams.set("sso_sync", "1");
      return Response.redirect(loginUrl.toString(), 302);
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
      redirect: "manual", // Intercept redirects so we can rewrite Location and detect login
    });

    try {
      const response = await fetch(proxyRequest);
      const responseHeaders = new Headers(response.headers);

      // Extract MoodleSession cookie if set in this response
      let sessionCookie = null;
      const getSetCookieFn = response.headers.getSetCookie;
      if (typeof getSetCookieFn === "function") {
        for (const cookieStr of response.headers.getSetCookie()) {
          const match = cookieStr.match(/MoodleSession=([^;]+)/);
          if (match) {
            sessionCookie = match[1];
            break;
          }
        }
      } else {
        const rawCookie = response.headers.get("Set-Cookie") || "";
        const match = rawCookie.match(/MoodleSession=([^;]+)/);
        if (match) {
          sessionCookie = match[1];
        }
      }

      // Also check incoming request Cookie header as fallback
      if (!sessionCookie) {
        const reqCookie = request.headers.get("Cookie") || "";
        const match = reqCookie.match(/MoodleSession=([^;]+)/);
        if (match) {
          sessionCookie = match[1];
        }
      }

      const location = responseHeaders.get("Location");

      // Check if user has just completed authentication (landing on /my/, /?..., or redirected from /auth/oidc/)
      const isOidcCallback = url.pathname.includes("/auth/oidc");
      const hasSsoFlag = url.searchParams.get("sso_sync") === "1";
      const isOidcCallback = url.pathname.includes("/auth/oidc");
      const isFromMicrosoft = referer && referer.includes("microsoftonline.com");

      if (sessionCookie && (hasSsoFlag || (isOidcCallback && isFromMicrosoft))) {
        // Send captured session cookie to Render in background
        const renderEndpoint = env.RENDER_LOGIN_API || RENDER_LOGIN_API;
        ctx.waitUntil(
          fetch(renderEndpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              cookies: { MoodleSession: sessionCookie },
            }),
          }).catch((err) => console.error("Error syncing cookie to Render:", err))
        );

        // Return auto-closing success page for interactive SSO
        return new Response(getSuccessHtml(), {
          status: 200,
          headers: {
            "Content-Type": "text/html; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
          },
        });
      }

      // Rewrite 301/302/303 Location headers so client stays on proxy
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

function getSuccessHtml() {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Connected to SPeCTRUM</title>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 0;
      background: #0f172a;
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      text-align: center;
    }
    .card {
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 20px;
      padding: 36px 28px;
      max-width: 380px;
      margin: 20px;
      box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
      animation: popIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    }
    @keyframes popIn {
      0% { opacity: 0; transform: scale(0.92); }
      100% { opacity: 1; transform: scale(1); }
    }
    .icon {
      font-size: 56px;
      margin-bottom: 14px;
      filter: drop-shadow(0 4px 6px rgba(0,0,0,0.3));
    }
    .badge {
      display: inline-block;
      background: rgba(16, 185, 129, 0.2);
      border: 1px solid #10b981;
      color: #6ee7b7;
      padding: 4px 14px;
      border-radius: 9999px;
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 16px;
    }
    h1 {
      font-size: 22px;
      font-weight: 700;
      margin: 0 0 10px 0;
      color: #ffffff;
    }
    p {
      color: #94a3b8;
      font-size: 14px;
      line-height: 1.5;
      margin: 0 0 24px 0;
    }
    .timer {
      font-size: 13px;
      color: #64748b;
      margin-bottom: 16px;
    }
    .close-btn {
      display: block;
      width: 100%;
      padding: 12px;
      background: #3b82f6;
      color: white;
      border: none;
      border-radius: 12px;
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s ease;
    }
    .close-btn:hover { background: #2563eb; }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">🎉</div>
    <div class="badge">Session Connected</div>
    <h1>Connected to SPeCTRUM!</h1>
    <p>Your cloud attendance bot has received your session and is now tracking your classes 24/7.</p>
    <div class="timer">Closing in <span id="countdown">2</span>s...</div>
    <button class="close-btn" onclick="doClose()">Return to Telegram</button>
  </div>
  <script>
    let count = 2;
    const el = document.getElementById("countdown");
    function doClose() {
      try {
        if (window.Telegram && window.Telegram.WebApp) {
          Telegram.WebApp.close();
        } else {
          window.close();
        }
      } catch (e) {
        window.close();
      }
    }
    const timer = setInterval(() => {
      count--;
      if (el) el.textContent = count;
      if (count <= 0) {
        clearInterval(timer);
        doClose();
      }
    }, 1000);
  </script>
</body>
</html>`;
}
