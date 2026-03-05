import React from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ArrowRight, Github, FileCode2, Code2 } from 'lucide-react';

export interface HeroProps {
  title: string;
  subtitle: string;
  description?: string;
  ctaText: string;
  ctaLink: string;
  secondaryCTAText?: string;
  secondaryCTALink?: string;
  image?: string;
  imageAlt?: string;
  className?: string;
}

export function Hero({
  title,
  subtitle,
  description,
  ctaText,
  ctaLink,
  secondaryCTAText,
  secondaryCTALink,
  image,
  imageAlt = 'Hero Image',
  className,
}: HeroProps) {
  return (
    <section className={cn('py-20 px-6 bg-gradient-to-b from-gray-50 to-white dark:from-gray-900 dark:to-gray-950', className)}>
      <div className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
        <div>
          <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold mb-4 bg-clip-text text-transparent bg-gradient-to-r from-primary-600 to-secondary-600 dark:from-primary-400 dark:to-secondary-400">
            {title}
          </h1>
          <h2 className="text-xl md:text-2xl mb-6 text-gray-600 dark:text-gray-300">
            {subtitle}
          </h2>
          {description && (
            <p className="text-lg mb-8 text-gray-600 dark:text-gray-300 max-w-xl">
              {description}
            </p>
          )}
          <div className="flex flex-wrap gap-4">
            <Button asChild size="lg">
              <Link href={ctaLink}>{ctaText}</Link>
            </Button>
            {secondaryCTAText && secondaryCTALink && (
              <Button asChild variant="outline" size="lg">
                <Link href={secondaryCTALink}>{secondaryCTAText}</Link>
              </Button>
            )}
          </div>
          <div className="mt-8 flex flex-col sm:flex-row sm:items-center gap-4 animate-slide-up [animation-delay:600ms]">
            <Link
              href="https://github.com/wyattowalsh/mcp-crawl4ai"
              className="inline-flex items-center text-sm text-gray-500 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 transition-colors duration-200"
              target="_blank"
              rel="noopener noreferrer"
            >
              <Github className="mr-2 h-5 w-5" />
              <span>Star on GitHub</span>
            </Link>
            <Link
              href="/docs/prd"
              className="inline-flex items-center text-sm text-gray-500 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 transition-colors duration-200"
            >
              <FileCode2 className="mr-2 h-5 w-5" />
              <span>Read the PRD</span>
            </Link>
            <Link
              href="/docs/contributing"
              className="inline-flex items-center text-sm text-gray-500 dark:text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 transition-colors duration-200"
            >
              <Code2 className="mr-2 h-5 w-5" />
              <span>How to Contribute</span>
            </Link>
          </div>
        </div>
        {image && (
          <div className="relative w-full h-[400px] lg:h-[500px]">
            <Image
              src={image}
              alt={imageAlt}
              fill
              className="object-contain"
              priority
            />
          </div>
        )}
      </div>
    </section>
  );
} 