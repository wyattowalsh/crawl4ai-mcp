import { DocsLayout } from 'fumadocs-ui/layouts/docs';
import type { ReactNode } from 'react';
import { baseOptions } from '@/app/layout.config';
import { source } from '@/lib/source';

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <DocsLayout 
      tree={source.pageTree} 
      {...baseOptions}
      banner={{
        dismissible: true,
        text: '🚀 MCP-Crawl4AI is currently in development. Check out the roadmap to see what\'s coming next!',
      }}
      sidebar={{
        defaultOpenLevel: 1,
        collapsible: true,
        toggleButton: true,
      }}
      toc={{
        title: 'On This Page',
        backToTop: true,
      }}
      pagination={{
        enabled: true,
      }}
    >
      {children}
    </DocsLayout>
  );
}
