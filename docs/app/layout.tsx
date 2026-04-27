import './global.css';
import { Providers } from './layout.config';
import { Inter, JetBrains_Mono } from 'next/font/google';
import type { Metadata } from 'next';

const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-inter',
});

const mono = JetBrains_Mono({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-mono',
});

export const metadata: Metadata = {
  title: {
    default: 'MCP-Crawl4AI | Advanced Web Crawling for AI',
    template: '%s | MCP-Crawl4AI',
  },
  description: 'A powerful Model Context Protocol server implementation for web crawling and data extraction',
  keywords: ['web crawling', 'MCP', 'AI', 'web extraction', 'web data', 'LLM', 'Claude', 'Model Context Protocol'],
  authors: [{ name: 'Crawl4AI Team' }],
  metadataBase: new URL('https://mcp-crawl4ai.w4w.dev'),
  openGraph: {
    type: 'website',
    locale: 'en_US',
    url: 'https://mcp-crawl4ai.w4w.dev',
    title: 'MCP-Crawl4AI | Advanced Web Crawling for AI',
    description: 'A powerful Model Context Protocol server implementation for web crawling and data extraction',
    siteName: 'MCP-Crawl4AI Documentation',
    images: [
      {
        url: 'https://mcp-crawl4ai.w4w.dev/og-image.jpg',
        width: 1200,
        height: 630,
        alt: 'MCP-Crawl4AI Logo',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'MCP-Crawl4AI | Advanced Web Crawling for AI',
    description: 'A powerful Model Context Protocol server implementation for web crawling and data extraction',
    creator: '@crawl4ai',
    images: ['https://mcp-crawl4ai.w4w.dev/og-image.jpg'],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning className={`${inter.variable} ${mono.variable}`}>
      <body className="min-h-screen bg-background">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
