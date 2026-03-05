import React from 'react';

export default function WhySection() {
  return (
    <section className="py-24 px-6 bg-gray-50 dark:bg-gray-900">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-white sm:text-4xl">
            Why Choose MCP-Crawl4AI?
          </h2>
          <p className="mt-4 text-lg text-gray-600 dark:text-gray-400 max-w-3xl mx-auto">
            Designed specifically for AI workflows, MCP-Crawl4AI bridges the gap between web data and AI models.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-md">
            <h3 className="text-xl font-semibold mb-3">AI-First Design</h3>
            <p>Built from the ground up for AI systems, providing context-aware data extraction.</p>
          </div>
          <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-md">
            <h3 className="text-xl font-semibold mb-3">No-Code Integration</h3>
            <p>Seamlessly connect with any MCP-compatible AI client without complex setup.</p>
          </div>
          <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-md">
            <h3 className="text-xl font-semibold mb-3">Ethically Designed</h3>
            <p>Respectful of website terms, robots.txt, and rate limits with privacy-first approach.</p>
          </div>
          <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-md">
            <h3 className="text-xl font-semibold mb-3">Open Source & Extensible</h3>
            <p>Fully open source with a modular architecture that's easy to extend and customize.</p>
          </div>
        </div>
      </div>
    </section>
  );
} 