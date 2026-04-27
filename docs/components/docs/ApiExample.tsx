"use client";

import React, { useState } from 'react';
import { Tabs, Tab } from 'fumadocs-ui/components/tabs';
import { CodeBlock } from '../ui/CodeBlock';
import { cn } from '@/lib/utils';

interface ApiExampleProps {
  title?: string;
  description?: string;
  endpoint?: string;
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  requestCode?: {
    json?: string;
    python?: string;
    javascript?: string;
    curl?: string;
  };
  responseCode?: {
    json?: string;
    python?: string;
    javascript?: string;
  };
  parameters?: Array<{
    name: string;
    type: string;
    required: boolean;
    description: string;
  }>;
  className?: string;
}

export const ApiExample: React.FC<ApiExampleProps> = ({
  title,
  description,
  endpoint,
  method = 'POST',
  requestCode,
  responseCode,
  parameters,
  className,
}) => {
  const [activeTab, setActiveTab] = useState<'request' | 'response'>('request');
  
  const methodColors = {
    GET: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300',
    POST: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
    PUT: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300',
    DELETE: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
    PATCH: 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300',
  };

  return (
    <div className={cn('my-8 rounded-lg border border-gray-200 dark:border-gray-800 overflow-hidden', className)}>
      {/* Header */}
      {(title || endpoint || description) && (
        <div className="border-b border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 p-4">
          {title && <h3 className="text-lg font-semibold mb-1">{title}</h3>}
          
          {endpoint && (
            <div className="flex items-center gap-2 my-2 font-mono text-sm">
              <span className={cn('px-2 py-1 rounded text-xs font-semibold', methodColors[method])}>
                {method}
              </span>
              <code className="bg-gray-100 dark:bg-gray-800 px-2 py-1 rounded">{endpoint}</code>
            </div>
          )}
          
          {description && <p className="text-gray-600 dark:text-gray-400 text-sm mt-2">{description}</p>}
        </div>
      )}

      {/* Parameters */}
      {parameters && parameters.length > 0 && (
        <div className="p-4 border-b border-gray-200 dark:border-gray-800">
          <h4 className="text-sm font-semibold mb-3">Parameters</h4>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
              <thead>
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Name</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Type</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Required</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {parameters.map((param) => (
                  <tr key={param.name}>
                    <td className="px-3 py-2 text-sm font-mono text-gray-800 dark:text-gray-200">{param.name}</td>
                    <td className="px-3 py-2 text-sm text-gray-600 dark:text-gray-400">{param.type}</td>
                    <td className="px-3 py-2 text-sm">
                      {param.required ? (
                        <span className="text-red-500 dark:text-red-400">Required</span>
                      ) : (
                        <span className="text-gray-500 dark:text-gray-400">Optional</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-sm text-gray-600 dark:text-gray-400">{param.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Code examples */}
      <div className="p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex space-x-2">
            <button
              className={cn(
                'px-3 py-1 text-sm rounded-md transition-colors',
                activeTab === 'request'
                  ? 'bg-primary-100 text-primary-800 dark:bg-primary-900/20 dark:text-primary-300'
                  : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
              )}
              onClick={() => setActiveTab('request')}
            >
              Request
            </button>
            <button
              className={cn(
                'px-3 py-1 text-sm rounded-md transition-colors',
                activeTab === 'response'
                  ? 'bg-primary-100 text-primary-800 dark:bg-primary-900/20 dark:text-primary-300'
                  : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
              )}
              onClick={() => setActiveTab('response')}
              disabled={!responseCode}
            >
              Response
            </button>
          </div>
        </div>

        {activeTab === 'request' && requestCode && (
          <Tabs items={Object.keys(requestCode).filter(key => !!requestCode[key as keyof typeof requestCode])}>
            {requestCode.json && (
              <Tab value="json">
                <CodeBlock
                  code={requestCode.json}
                  language="json"
                  showLineNumbers
                />
              </Tab>
            )}
            {requestCode.python && (
              <Tab value="python">
                <CodeBlock
                  code={requestCode.python}
                  language="python"
                  showLineNumbers
                />
              </Tab>
            )}
            {requestCode.javascript && (
              <Tab value="javascript">
                <CodeBlock
                  code={requestCode.javascript}
                  language="javascript"
                  showLineNumbers
                />
              </Tab>
            )}
            {requestCode.curl && (
              <Tab value="curl">
                <CodeBlock
                  code={requestCode.curl}
                  language="bash"
                  showLineNumbers
                />
              </Tab>
            )}
          </Tabs>
        )}

        {activeTab === 'response' && responseCode && (
          <Tabs items={Object.keys(responseCode).filter(key => !!responseCode[key as keyof typeof responseCode])}>
            {responseCode.json && (
              <Tab value="json">
                <CodeBlock
                  code={responseCode.json}
                  language="json"
                  showLineNumbers
                />
              </Tab>
            )}
            {responseCode.python && (
              <Tab value="python">
                <CodeBlock
                  code={responseCode.python}
                  language="python"
                  showLineNumbers
                />
              </Tab>
            )}
            {responseCode.javascript && (
              <Tab value="javascript">
                <CodeBlock
                  code={responseCode.javascript}
                  language="javascript"
                  showLineNumbers
                />
              </Tab>
            )}
          </Tabs>
        )}
      </div>
    </div>
  );
}; 
