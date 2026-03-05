import Link from 'next/link';
import Image from 'next/image';
import { cn } from '../../lib/utils';

// Icons
import { 
  Globe, 
  Cpu, 
  Database, 
  Search, 
  BrainCircuit,
  Bot,
  Network
} from 'lucide-react';

// Define button styles
const baseButtonStyles = "rounded-lg font-medium transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-gray-900 shadow-sm hover:shadow-md";
const primaryButtonStyles = "bg-gradient-to-r from-blue-600 to-teal-500 hover:from-blue-700 hover:to-teal-600 text-white";
const secondaryButtonStyles = "bg-gray-100 hover:bg-gray-200 text-gray-900 border border-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 dark:text-gray-100 dark:border-gray-700";
const largeButtonStyles = "px-6 py-3 text-lg";

export default function Home() {
  return (
    <div className="flex h-screen overflow-hidden">
      <div className="mesh-gradient grid-pattern relative w-full flex items-center">
        {/* Animated background elements */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute -top-20 -left-20 w-72 h-72 bg-blue-500/10 rounded-full blur-3xl animate-float"></div>
          <div className="absolute top-1/3 -right-20 w-80 h-80 bg-teal-500/10 rounded-full blur-3xl animate-float" style={{ animationDelay: '2s' }}></div>
          <div className="absolute -bottom-40 left-1/4 w-96 h-96 bg-purple-500/10 rounded-full blur-3xl animate-float" style={{ animationDelay: '4s' }}></div>
          
          {/* Web crawler visual elements */}
          <div className="absolute top-1/4 left-1/3 opacity-20 dark:opacity-30">
            <Network className="w-16 h-16 text-blue-500 animate-pulse-slow" />
          </div>
          <div className="absolute bottom-1/4 right-1/3 opacity-20 dark:opacity-30">
            <Globe className="w-14 h-14 text-teal-500 animate-pulse-slow" style={{ animationDelay: '2s' }} />
          </div>
          <div className="absolute top-2/3 left-1/5 opacity-20 dark:opacity-30">
            <Database className="w-12 h-12 text-indigo-500 animate-pulse-slow" style={{ animationDelay: '3.5s' }} />
          </div>
          <div className="absolute top-1/3 right-1/4 opacity-20 dark:opacity-30">
            <Search className="w-10 h-10 text-purple-500 animate-pulse-slow" style={{ animationDelay: '1.5s' }} />
          </div>
        </div>
        
        {/* Hero content */}
        <div className="container mx-auto px-6 z-10 flex flex-col lg:flex-row items-center justify-between gap-12">
          {/* Left text content */}
          <div className="w-full lg:w-1/2 space-y-6 text-center lg:text-left">
            <div className="space-y-2">
              <h1 className="text-4xl md:text-5xl lg:text-6xl font-extrabold tracking-tight">
                <span className="gradient-text">MCP-Crawl4AI</span>
              </h1>
              <p className="text-2xl md:text-3xl font-semibold text-gray-700 dark:text-gray-300">
                Web Crawling for AI Knowledge Context
              </p>
            </div>
            
            <p className="text-lg text-gray-600 dark:text-gray-400 max-w-xl mx-auto lg:mx-0">
              Seamlessly extract and structure web data for AI assistants through the Model Context Protocol. Enhance your AI's knowledge with real-time web intelligence.
            </p>
            
            <div className="flex flex-col sm:flex-row gap-4 justify-center lg:justify-start pt-4">
              <Link 
                href="/docs" 
                className={cn(baseButtonStyles, primaryButtonStyles, largeButtonStyles, "flex items-center justify-center gap-2")}
              >
                <span>Get Started</span>
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 7l5 5m0 0l-5 5m5-5H6"></path>
                </svg>
              </Link>
              <Link 
                href="https://github.com/wyattowalsh/mcp-crawl4ai" 
                className={cn(baseButtonStyles, secondaryButtonStyles, largeButtonStyles, "flex items-center justify-center gap-2")}
                target="_blank"
                rel="noopener noreferrer"
              >
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.477 2 12c0 4.42 2.865 8.167 6.839 9.49.5.092.682-.217.682-.482 0-.237-.008-.866-.013-1.7-2.782.603-3.369-1.34-3.369-1.34-.454-1.156-1.11-1.464-1.11-1.464-.908-.62.069-.608.069-.608 1.003.07 1.531 1.03 1.531 1.03.892 1.529 2.341 1.087 2.91.832.092-.646.35-1.086.636-1.336-2.22-.253-4.555-1.11-4.555-4.943 0-1.091.39-1.984 1.029-2.683-.103-.253-.446-1.27.098-2.647 0 0 .84-.268 2.75 1.026A9.578 9.578 0 0112 6.836c.85.004 1.705.114 2.504.336 1.909-1.294 2.747-1.026 2.747-1.026.546 1.377.203 2.394.1 2.647.64.699 1.028 1.592 1.028 2.683 0 3.842-2.339 4.687-4.566 4.935.359.309.678.919.678 1.852 0 1.336-.012 2.415-.012 2.743 0 .267.18.578.688.48C19.138 20.164 22 16.418 22 12c0-5.523-4.477-10-10-10z"></path>
                </svg>
                <span>GitHub</span>
              </Link>
            </div>
          </div>
          
          {/* Right illustration */}
          <div className="w-full lg:w-1/2 flex justify-center lg:justify-end">
            <div className="relative w-full max-w-md">
              <div className="absolute inset-0 bg-gradient-to-r from-blue-500/20 to-teal-500/20 rounded-full blur-3xl transform -translate-x-4 translate-y-4"></div>
              <div className="relative glass-effect rounded-2xl overflow-hidden border border-white/20 shadow-xl animate-float">
                <div className="p-6 bg-opacity-90">
                  {/* Tech illustration representing web crawling + LLM */}
                  <div className="aspect-square relative flex items-center justify-center">
                    <div className="absolute inset-0 flex items-center justify-center">
                      <Globe className="w-64 h-64 text-blue-500/20" />
                    </div>
                    <div className="relative z-10 flex flex-col items-center gap-6">
                      <div className="flex items-center gap-6">
                        <div className="rounded-full bg-blue-100 dark:bg-blue-900/30 p-4 shadow-lg">
                          <Globe className="w-12 h-12 text-blue-600 dark:text-blue-400" />
                        </div>
                        <svg width="60" height="6" viewBox="0 0 60 6" fill="none" xmlns="http://www.w3.org/2000/svg">
                          <path d="M0 3H60" stroke="currentColor" strokeWidth="2" strokeDasharray="6 4" className="text-gray-400" />
                        </svg>
                        <div className="rounded-full bg-teal-100 dark:bg-teal-900/30 p-4 shadow-lg">
                          <Database className="w-12 h-12 text-teal-600 dark:text-teal-400" />
                        </div>
                      </div>
                      
                      <svg width="6" height="40" viewBox="0 0 6 40" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M3 0V40" stroke="currentColor" strokeWidth="2" strokeDasharray="6 4" className="text-gray-400" />
                      </svg>
                      
                      <div className="rounded-full bg-purple-100 dark:bg-purple-900/30 p-5 shadow-lg">
                        <BrainCircuit className="w-14 h-14 text-purple-600 dark:text-purple-400" />
                      </div>
                      
                      <svg width="6" height="40" viewBox="0 0 6 40" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M3 0V40" stroke="currentColor" strokeWidth="2" strokeDasharray="6 4" className="text-gray-400" />
                      </svg>
                      
                      <div className="rounded-full bg-indigo-100 dark:bg-indigo-900/30 p-4 shadow-lg">
                        <Bot className="w-12 h-12 text-indigo-600 dark:text-indigo-400" />
                      </div>
                    </div>
                  </div>
                  
                  {/* Code example */}
                  <div className="mt-4 bg-gray-900 rounded-lg p-4 text-sm font-mono text-gray-300 overflow-hidden">
                    <div className="opacity-70">// Connect MCP-Crawl4AI to your AI assistant</div>
                    <div className="text-blue-400">const</div>
                    <div><span className="text-green-400">assistant</span> = <span className="text-blue-400">new</span> <span className="text-yellow-400">AI</span>();</div>
                    <div><span className="text-green-400">assistant</span>.<span className="text-blue-400">addMcpTool</span>({</div>
                    <div>&nbsp;&nbsp;name: <span className="text-orange-400">"mcp_Browser_web_crawler"</span>,</div>
                    <div>&nbsp;&nbsp;url: <span className="text-orange-400">"http://localhost:8000"</span></div>
                    <div>});</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
