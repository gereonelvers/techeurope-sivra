/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emit a self-contained server bundle for the Docker/Railway deploy.
  output: "standalone",
  reactStrictMode: true,
};

module.exports = nextConfig;
