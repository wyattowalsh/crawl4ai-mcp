import type { DocsLayoutProps } from 'fumadocs-ui/layouts/docs';
import type { HomeLayoutProps } from 'fumadocs-ui/layouts/home';
import { RootProvider } from 'fumadocs-ui/provider';
import { ReactNode } from 'react';

/**
 * Shared layout configurations
 *
 * you can customise layouts individually from:
 * Home Layout: app/(home)/layout.tsx
 * Docs Layout: app/docs/layout.tsx
 */
export function Providers({ children }: { children: ReactNode }) {
  return <RootProvider>{children}</RootProvider>;
}

export const baseOptions: Partial<DocsLayoutProps & HomeLayoutProps> = {
  nav: {
    title: 'MCP-Crawl4AI',
    enabled: true,
    url: '/',
    component: undefined,
    children: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="w-6 h-6"
      >
        <path d="M5 3a2 2 0 0 0-2 2v14c0 1.1.9 2 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2H5Z" />
        <path d="M8 12h8" />
        <path d="M12 8v8" />
      </svg>
    ),
  },
  githubUrl: 'https://github.com/wyattowalsh/mcp-crawl4ai',
  links: [
    {
      text: 'Documentation',
      url: '/docs',
    },
    {
      text: 'PRD',
      url: '/docs/prd',
    },
    {
      text: 'Contributing',
      url: '/docs/contributing',
    },
  ],
  themeSwitch: {
    enabled: true,
  },
  sidebar: {
    defaultOpenLevel: 1,
  },
};
