import React from 'react';
import { CodeBlock } from '@/components/ui/CodeBlock';

export default function IntegrationExamples() {
  const pythonExample = `import asyncio
from mcp_crawl4ai import MCPServer

async def main():
    server = MCPServer()
    await server.start()
    
    # Server will respond to MCP client requests
    print("MCP-Crawl4AI server running on port 8000")
    
    # Keep the server running
    try:
        await asyncio.Future()
    except KeyboardInterrupt:
        await server.stop()

if __name__ == "__main__":
    asyncio.run(main())`;

  const claudeExample = `Human: Can you find the latest research on quantum computing advancements?

Claude: I'll search for the latest quantum computing research. Let me use MCP-Crawl4AI to find recent publications.

<mcp:function>
{
  "name": "crawl",
  "arguments": {
    "url": "https://arxiv.org/search/quant-ph?query=quantum+computing&searchtype=all&abstracts=show&order=-announced_date_first&size=5"
  }
}
</mcp:function>

Based on the latest research papers I found, here are the most recent quantum computing advancements...`;

  return (
    <section className="py-24 px-6 bg-white dark:bg-gray-950">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-white sm:text-4xl">
            Easy Integration
          </h2>
          <p className="mt-4 text-lg text-gray-600 dark:text-gray-400 max-w-3xl mx-auto">
            MCP-Crawl4AI works seamlessly with any MCP-compatible client, including Claude and GPT.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          <div>
            <h3 className="text-xl font-semibold mb-4 text-gray-900 dark:text-white">Server Setup</h3>
            <div className="rounded-lg overflow-hidden">
              <CodeBlock language="python" code={pythonExample} />
            </div>
          </div>
          
          <div>
            <h3 className="text-xl font-semibold mb-4 text-gray-900 dark:text-white">Claude Integration</h3>
            <div className="rounded-lg overflow-hidden">
              <CodeBlock language="markdown" code={claudeExample} />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
} 