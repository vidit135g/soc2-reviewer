/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  poweredByHeader: false,
  // Next's built-in proxy (used by `rewrites` below) defaults to a 30s
  // upstream-response timeout. Chat requests run an LLM completion that
  // can take 30–90s on cloud providers and longer for Ollama cold starts,
  // so we bump this to 5 minutes. Without it the proxy drops the socket
  // mid-LLM-call and the browser sees ECONNRESET / "socket hang up".
  experimental: {
    typedRoutes: false,
    proxyTimeout: 5 * 60 * 1000,
  },
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || 'http://backend:8000';
    return [
      { source: '/api/backend/:path*', destination: `${backendUrl}/api/:path*` },
      { source: '/health/backend', destination: `${backendUrl}/health` },
    ];
  },
};

module.exports = nextConfig;
