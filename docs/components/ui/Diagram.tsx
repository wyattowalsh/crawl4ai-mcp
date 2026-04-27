"use client";

import React, { useEffect, useRef, useState } from 'react';
import { cn } from '@/lib/utils';
import mermaid from 'mermaid';

interface DiagramProps {
  definition: string;
  className?: string;
  caption?: string;
  theme?: 'default' | 'dark' | 'forest' | 'neutral';
}

export const Diagram: React.FC<DiagramProps> = ({
  definition,
  className,
  caption,
  theme = 'default',
}) => {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [rendered, setRendered] = useState(false);

  useEffect(() => {
    if (ref.current) {
      try {
        mermaid.initialize({
          startOnLoad: true,
          theme: theme,
          securityLevel: 'loose',
          flowchart: {
            htmlLabels: true,
            curve: 'basis',
          },
        });
        
        mermaid.render('mermaid-diagram', definition)
          .then(({ svg, bindFunctions }) => {
            if (ref.current) {
              ref.current.innerHTML = svg;
              if (bindFunctions) bindFunctions(ref.current);
              setRendered(true);
              setError(null);
            }
          })
          .catch((err) => {
            console.error('Mermaid rendering error:', err);
            setError(`Diagram rendering error: ${err.message}`);
          });
      } catch (err: any) {
        console.error('Mermaid initialization error:', err);
        setError(`Diagram initialization error: ${err.message}`);
      }
    }
  }, [definition, theme]);

  return (
    <div className={cn('my-6', className)}>
      {error ? (
        <div className="p-4 border border-red-200 bg-red-50 dark:bg-red-900/20 dark:border-red-800 rounded-md text-red-700 dark:text-red-300">
          <p className="font-mono text-sm whitespace-pre-wrap">{error}</p>
          <pre className="mt-2 p-2 bg-gray-100 dark:bg-gray-800 overflow-x-auto rounded text-xs">
            {definition}
          </pre>
        </div>
      ) : (
        <div className="flex flex-col items-center">
          <div 
            ref={ref} 
            className={cn(
              'w-full overflow-x-auto p-4 rounded-lg bg-white dark:bg-gray-900',
              'shadow-sm border border-gray-200 dark:border-gray-800',
              !rendered && 'min-h-[100px] flex items-center justify-center'
            )}
          >
            {!rendered && <span className="text-gray-500 dark:text-gray-400">Rendering diagram...</span>}
          </div>
          {caption && (
            <div className="mt-2 text-sm text-gray-500 dark:text-gray-400 text-center">
              {caption}
            </div>
          )}
        </div>
      )}
    </div>
  );
}; 
