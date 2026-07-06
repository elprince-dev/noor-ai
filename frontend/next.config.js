/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',  // Static HTML export for S3 + CloudFront
  trailingSlash: true,  // Better compatibility with S3 routing
};

module.exports = nextConfig;
