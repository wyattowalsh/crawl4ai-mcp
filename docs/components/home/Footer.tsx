import React from 'react';
import Link from 'next/link';
import Image from 'next/image';

export default function Footer() {
  return (
    <footer className="w-full border-t border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/50 py-12">
      <div className="max-w-7xl mx-auto px-4">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
          <div className="space-y-4">
            <Link href="/" className="flex items-center gap-2">
              <Image
                src="/logo.png"
                alt="MCP-Crawl4AI Logo"
                width={40}
                height={40}
                className="w-8 h-8"
              />
              <span className="font-bold text-xl">Crawl4AI</span>
              <span className="text-xs bg-blue-100 dark:bg-blue-900/50 text-blue-800 dark:text-blue-300 px-1.5 py-0.5 rounded">MCP</span>
            </Link>
            <p className="text-sm text-slate-600 dark:text-slate-400 max-w-xs">
              Advanced Python-based web crawling for AI applications with uvx/uv optimization and MCP integration.
            </p>
            <div className="flex items-center gap-4">
              <a 
                href="https://github.com/wyattowalsh/mcp-crawl4ai" 
                target="_blank" 
                rel="noopener noreferrer"
                className="text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 transition-colors"
              >
                <svg className="w-5 h-5" aria-hidden="true" fill="currentColor" viewBox="0 0 24 24">
                  <path fillRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clipRule="evenodd"></path>
                </svg>
                <span className="sr-only">GitHub</span>
              </a>
              <a 
                href="https://twitter.com/crawl4ai" 
                target="_blank" 
                rel="noopener noreferrer"
                className="text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 transition-colors"
              >
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M8.29 20.251c7.547 0 11.675-6.253 11.675-11.675 0-.178 0-.355-.012-.53A8.348 8.348 0 0022 5.92a8.19 8.19 0 01-2.357.646 4.118 4.118 0 001.804-2.27 8.224 8.224 0 01-2.605.996 4.107 4.107 0 00-6.993 3.743 11.65 11.65 0 01-8.457-4.287 4.106 4.106 0 001.27 5.477A4.072 4.072 0 012.8 9.713v.052a4.105 4.105 0 003.292 4.022 4.095 4.095 0 01-1.853.07 4.108 4.108 0 003.834 2.85A8.233 8.233 0 012 18.407a11.616 11.616 0 006.29 1.84"></path>
                </svg>
                <span className="sr-only">Twitter</span>
              </a>
            </div>
          </div>
          
          <div>
            <h3 className="font-medium text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-4">Documentation</h3>
            <ul className="space-y-2">
              <li>
                <Link href="/docs/getting-started" className="text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors text-sm">Getting Started</Link>
              </li>
              <li>
                <Link href="/docs/api" className="text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors text-sm">API Reference</Link>
              </li>
              <li>
                <Link href="/docs/mcp" className="text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors text-sm">MCP Integration</Link>
              </li>
              <li>
                <Link href="/docs/examples" className="text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors text-sm">Examples</Link>
              </li>
            </ul>
          </div>
          
          <div>
            <h3 className="font-medium text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-4">Resources</h3>
            <ul className="space-y-2">
              <li>
                <Link href="/docs/blog" className="text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors text-sm">Blog</Link>
              </li>
              <li>
                <Link href="/docs/changelog" className="text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors text-sm">Changelog</Link>
              </li>
              <li>
                <Link href="/docs/roadmap" className="text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors text-sm">Roadmap</Link>
              </li>
              <li>
                <Link href="/docs/pricing" className="text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors text-sm">Pricing</Link>
              </li>
            </ul>
          </div>
          
          <div>
            <h3 className="font-medium text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-4">Legal</h3>
            <ul className="space-y-2">
              <li>
                <Link href="/docs/privacy" className="text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors text-sm">Privacy Policy</Link>
              </li>
              <li>
                <Link href="/docs/terms" className="text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors text-sm">Terms of Service</Link>
              </li>
              <li>
                <Link href="/docs/ethics" className="text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors text-sm">Ethical Crawling</Link>
              </li>
              <li>
                <Link href="/docs/attribution" className="text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors text-sm">Attribution</Link>
              </li>
            </ul>
          </div>
        </div>
        
        <div className="mt-12 pt-8 border-t border-slate-200 dark:border-slate-800 flex flex-col md:flex-row justify-between items-center">
          <p className="text-sm text-slate-500 dark:text-slate-400 mb-4 md:mb-0">
            &copy; {new Date().getFullYear()} MCP-Crawl4AI. All rights reserved.
          </p>
          <p className="text-xs text-slate-400 dark:text-slate-500">
            <span className="font-mono">Built with Python 3.10+, UV, and UVX optimization</span>
          </p>
        </div>
      </div>
    </footer>
  );
} 