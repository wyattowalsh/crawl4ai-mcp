import React from 'react';
import { CheckCircle2, XCircle, MinusCircle, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

type FeatureStatus = 'yes' | 'no' | 'partial' | 'planned';
type FeatureGroup = 'core' | 'advanced' | 'pro' | 'enterprise';

interface Feature {
  name: string;
  description?: string;
  crawl4aiMcp: FeatureStatus;
  alternatives: Record<string, FeatureStatus>;
  group?: FeatureGroup;
}

interface ComparisonTableProps {
  features: Feature[];
  alternativeNames: string[];
  className?: string;
  showGroups?: boolean;
}

const statusIcons: Record<FeatureStatus, React.ReactNode> = {
  yes: <CheckCircle2 className="h-5 w-5 text-green-500" />,
  no: <XCircle className="h-5 w-5 text-red-500" />,
  partial: <MinusCircle className="h-5 w-5 text-yellow-500" />,
  planned: <AlertCircle className="h-5 w-5 text-blue-500" />
};

export const ComparisonTable: React.FC<ComparisonTableProps> = ({
  features,
  alternativeNames,
  className,
  showGroups = true
}) => {
  const groupedFeatures = features.reduce((acc, feature) => {
    const group = feature.group || 'core';
    if (!acc[group]) {
      acc[group] = [];
    }
    acc[group].push(feature);
    return acc;
  }, {} as Record<FeatureGroup, Feature[]>);
  
  const groupOrder: FeatureGroup[] = ['core', 'advanced', 'pro', 'enterprise'];
  const groupLabels: Record<FeatureGroup, string> = {
    core: 'Core Features',
    advanced: 'Advanced Features',
    pro: 'Pro Features',
    enterprise: 'Enterprise Features'
  };

  return (
    <div className={cn('overflow-x-auto my-8', className)}>
      <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 table-fixed">
        <thead className="bg-gray-50 dark:bg-gray-800">
          <tr>
            <th scope="col" className="py-3 px-4 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider w-1/4">
              Feature
            </th>
            <th scope="col" className="py-3 px-4 text-center text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider bg-primary-50 dark:bg-primary-900/20 w-1/6">
              MCP-Crawl4AI
            </th>
            {alternativeNames.map((name) => (
              <th 
                key={name} 
                scope="col" 
                className="py-3 px-4 text-center text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider w-1/6"
              >
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-800">
          {showGroups ? (
            groupOrder.map(group => {
              const groupFeatures = groupedFeatures[group];
              if (!groupFeatures?.length) return null;
              
              return (
                <React.Fragment key={group}>
                  <tr className="bg-gray-100 dark:bg-gray-800/50">
                    <td 
                      colSpan={alternativeNames.length + 2}
                      className="py-2 px-4 text-sm font-semibold text-gray-700 dark:text-gray-200"
                    >
                      {groupLabels[group]}
                    </td>
                  </tr>
                  {groupFeatures.map((feature, idx) => renderFeatureRow(feature, alternativeNames, idx))}
                </React.Fragment>
              );
            })
          ) : (
            features.map((feature, idx) => renderFeatureRow(feature, alternativeNames, idx))
          )}
        </tbody>
      </table>
      
      <div className="mt-4 flex flex-wrap gap-4 text-sm text-gray-600 dark:text-gray-400">
        <div className="flex items-center">
          <CheckCircle2 className="h-4 w-4 text-green-500 mr-1" />
          <span>Supported</span>
        </div>
        <div className="flex items-center">
          <MinusCircle className="h-4 w-4 text-yellow-500 mr-1" />
          <span>Partial Support</span>
        </div>
        <div className="flex items-center">
          <AlertCircle className="h-4 w-4 text-blue-500 mr-1" />
          <span>Planned</span>
        </div>
        <div className="flex items-center">
          <XCircle className="h-4 w-4 text-red-500 mr-1" />
          <span>Not Supported</span>
        </div>
      </div>
    </div>
  );
};

function renderFeatureRow(feature: Feature, alternativeNames: string[], idx: number) {
  return (
    <tr key={feature.name} className={idx % 2 === 0 ? 'bg-white dark:bg-gray-900' : 'bg-gray-50 dark:bg-gray-800/20'}>
      <td className="py-3 px-4">
        <div className="text-sm font-medium text-gray-900 dark:text-gray-100">{feature.name}</div>
        {feature.description && (
          <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">{feature.description}</div>
        )}
      </td>
      
      <td className="py-3 px-4 text-center bg-primary-50 dark:bg-primary-900/20">
        <div className="flex justify-center">
          {statusIcons[feature.crawl4aiMcp]}
        </div>
      </td>
      
      {alternativeNames.map((name) => (
        <td key={name} className="py-3 px-4 text-center">
          <div className="flex justify-center">
            {statusIcons[feature.alternatives[name] || 'no']}
          </div>
        </td>
      ))}
    </tr>
  );
} 