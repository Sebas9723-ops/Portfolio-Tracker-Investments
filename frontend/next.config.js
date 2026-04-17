/** @type {import('next').NextConfig} */
const withBundleAnalyzer = require("@next/bundle-analyzer")({
  enabled: process.env.ANALYZE === "true",
});

const nextConfig = {
  images: {
    domains: ["finnhub.io", "static.finnhub.io"],
  },
};

module.exports = withBundleAnalyzer(nextConfig);
