import React, { useState } from 'react';
import { motion } from 'framer-motion';

interface TabProps {
  id: string;
  label: string;
  icon?: React.ReactNode;
  count?: number;
}

interface TabbedInterfaceProps {
  tabs: TabProps[];
  defaultTab?: string;
  children: React.ReactNode[];
  isDarkMode?: boolean;
}

const TabbedInterface: React.FC<TabbedInterfaceProps> = ({
  tabs,
  defaultTab,
  children,
  isDarkMode = false,
}) => {
  const [activeTab, setActiveTab] = useState<string>(defaultTab || tabs[0]?.id || '');

  const handleTabChange = (tabId: string) => {
    setActiveTab(tabId);
  };

  return (
    <div className="rounded-lg shadow overflow-hidden">
      {/* Tab Navigation */}
      <div className={`flex border-b ${isDarkMode ? 'border-gray-700 bg-gray-700' : 'border-gray-200 bg-gray-50'}`}>
        {tabs.map((tab, index) => (
          <button
            key={tab.id}
            onClick={() => handleTabChange(tab.id)}
            className={`
              flex items-center gap-2 px-4 py-3 transition-colors font-medium
              ${activeTab === tab.id 
                ? (isDarkMode 
                    ? 'text-white border-b-2 border-blue-500' 
                    : 'text-blue-600 border-b-2 border-blue-500') 
                : (isDarkMode 
                    ? 'text-gray-300 hover:text-gray-100' 
                    : 'text-gray-600 hover:text-gray-900')
              }
            `}
          >
            {tab.icon}
            {tab.label}
            {tab.count !== undefined && (
              <span className={`
                ml-1 px-2 py-0.5 text-xs rounded-full 
                ${activeTab === tab.id 
                  ? (isDarkMode ? 'bg-blue-700 text-white' : 'bg-blue-100 text-blue-800') 
                  : (isDarkMode ? 'bg-gray-600 text-gray-200' : 'bg-gray-200 text-gray-700')
                }
              `}>
                {tab.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className={`transition-colors ${isDarkMode ? 'bg-gray-800' : 'bg-white'}`}>
        {children.map((child, index) => (
          <div 
            key={tabs[index]?.id || index}
            className={activeTab === tabs[index]?.id ? 'block' : 'hidden'}
          >
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
            >
              {child}
            </motion.div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default TabbedInterface;
