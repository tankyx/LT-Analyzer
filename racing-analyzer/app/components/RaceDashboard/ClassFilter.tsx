import React from 'react';

interface ClassFilterProps {
  selectedClass: string;
  onClassChange: (classValue: string) => void;
  isDarkMode?: boolean;
  teamCount?: Record<string, number>; // To show team counts per class
}

const ClassFilter: React.FC<ClassFilterProps> = ({ 
  selectedClass, 
  onClassChange,
  isDarkMode = false,
  teamCount = { all: 0, '1': 0, '2': 0 }
}) => {
  return (
    <div className="mb-4 flex items-center">
      <label className={`mr-2 font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
        Filter by Class:
      </label>
      <div className={`inline-flex rounded-md shadow-sm`}>
        <button
          type="button"
          onClick={() => onClassChange('all')}
          className={`
            px-4 py-2 text-sm font-medium rounded-l-md border
            ${selectedClass === 'all'
              ? (isDarkMode
                ? 'bg-blue-600 text-white border-blue-700'
                : 'bg-blue-600 text-white border-blue-600')
              : (isDarkMode
                ? 'bg-gray-700 text-gray-300 border-gray-600 hover:bg-gray-600'
                : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50')
            }
          `}
        >
          All Classes
          {teamCount?.all > 0 && (
            <span className={`ml-1.5 px-1.5 py-0.5 text-xs rounded-full inline-flex items-center justify-center
              ${selectedClass === 'all' 
                ? (isDarkMode ? 'bg-blue-500 text-white' : 'bg-blue-100 text-blue-800') 
                : (isDarkMode ? 'bg-gray-600 text-gray-200' : 'bg-gray-200 text-gray-700')
              }`}
            >
              {teamCount.all}
            </span>
          )}
        </button>
        <button
          type="button"
          onClick={() => onClassChange('1')}
          className={`
            px-4 py-2 text-sm font-medium border-t border-b border-r
            ${selectedClass === '1'
              ? (isDarkMode
                ? 'bg-blue-600 text-white border-blue-700'
                : 'bg-blue-600 text-white border-blue-600')
              : (isDarkMode
                ? 'bg-gray-700 text-gray-300 border-gray-600 hover:bg-gray-600'
                : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50')
            }
          `}
        >
          Class 1
          {teamCount?.['1'] > 0 && (
            <span className={`ml-1.5 px-1.5 py-0.5 text-xs rounded-full inline-flex items-center justify-center
              ${selectedClass === '1' 
                ? (isDarkMode ? 'bg-blue-500 text-white' : 'bg-blue-100 text-blue-800') 
                : (isDarkMode ? 'bg-gray-600 text-gray-200' : 'bg-gray-200 text-gray-700')
              }`}
            >
              {teamCount['1']}
            </span>
          )}
        </button>
        <button
          type="button"
          onClick={() => onClassChange('2')}
          className={`
            px-4 py-2 text-sm font-medium rounded-r-md border-t border-b border-r
            ${selectedClass === '2'
              ? (isDarkMode
                ? 'bg-blue-600 text-white border-blue-700'
                : 'bg-blue-600 text-white border-blue-600')
              : (isDarkMode
                ? 'bg-gray-700 text-gray-300 border-gray-600 hover:bg-gray-600'
                : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50')
            }
          `}
        >
          Class 2
          {teamCount?.['2'] > 0 && (
            <span className={`ml-1.5 px-1.5 py-0.5 text-xs rounded-full inline-flex items-center justify-center
              ${selectedClass === '2' 
                ? (isDarkMode ? 'bg-blue-500 text-white' : 'bg-blue-100 text-blue-800') 
                : (isDarkMode ? 'bg-gray-600 text-gray-200' : 'bg-gray-200 text-gray-700')
              }`}
            >
              {teamCount['2']}
            </span>
          )}
        </button>
      </div>
    </div>
  );
};

export default ClassFilter;
