import Link from 'next/link';
import { ArrowRight, ExternalLink } from 'lucide-react';

const primaryLinkClasses =
  'inline-flex items-center gap-2 rounded-lg bg-slate-900 px-5 py-3 font-medium text-white transition hover:bg-slate-700 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-200';

const secondaryLinkClasses =
  'inline-flex items-center gap-2 rounded-lg border border-slate-300 px-5 py-3 font-medium text-slate-900 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-100 dark:hover:bg-slate-900';

export default function Home() {
  return (
    <main className="mx-auto flex min-h-[calc(100vh-4rem)] w-full max-w-6xl items-center px-6 py-16">
      <div className="grid gap-12 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)] lg:items-center">
        <section className="space-y-6">
          <div className="inline-flex rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-sm font-medium text-sky-700 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-300">
            Documentation for MCP-Crawl4AI
          </div>
          <div className="space-y-4">
            <h1 className="text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl dark:text-slate-50">
              Crawl the web for AI workflows with a focused MCP server.
            </h1>
            <p className="max-w-2xl text-lg text-slate-600 dark:text-slate-300">
              MCP-Crawl4AI exposes a clean Model Context Protocol interface for scraping, crawling, session
              management, and artifact retrieval on top of Crawl4AI and FastMCP.
            </p>
          </div>
          <div className="flex flex-wrap gap-4">
            <Link href="/docs" className={primaryLinkClasses}>
              Read the docs
              <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              href="https://github.com/wyattowalsh/mcp-crawl4ai"
              className={secondaryLinkClasses}
              target="_blank"
              rel="noreferrer"
            >
              View on GitHub
              <ExternalLink className="h-4 w-4" />
            </Link>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-slate-50 p-6 shadow-sm dark:border-slate-800 dark:bg-slate-950">
          <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-50">What you get</h2>
          <ul className="mt-4 space-y-3 text-slate-600 dark:text-slate-300">
            <li>• Canonical <code>scrape</code> and <code>crawl</code> tools for live web access</li>
            <li>• Session-aware workflows with explicit close and artifact retrieval endpoints</li>
            <li>• Documentation for architecture, features, API reference, roadmap, and contributing</li>
          </ul>
        </section>
      </div>
    </main>
  );
}
