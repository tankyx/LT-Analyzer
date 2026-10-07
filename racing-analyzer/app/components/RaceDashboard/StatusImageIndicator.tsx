import React from 'react';

interface StatusImageIndicatorProps {
  status?: string;
  size?: 'sm' | 'md' | 'lg';
}

// Mapping of internal status values to image names
const STATUS_IMAGE_MAP: Record<string, string> = {
  'Pit-in': 'st_in.png',
  'Pit-out': 'st_out.png',
  'On Track': 'st_run.png',
  'Finished': 'st_finish.png',
  'Stopped': 'st_stop.png',
  'Up': 'st_up.png',
  'Down': 'st_down.png',
  'Lapped': 'st_l.png'
};

// Base URL for the status images
const IMAGE_BASE_URL = 'https://www.apex-timing.com/live-timing/commonv2/images/';

const StatusImageIndicator: React.FC<StatusImageIndicatorProps> = ({ status = 'On Track', size = 'md' }) => {
  // Get the image URL based on the status
  const imageFile = STATUS_IMAGE_MAP[status] || 'st_run.png';
  const imageUrl = `${IMAGE_BASE_URL}${imageFile}`;
  
  // Determine size class
  const sizeClass = {
    'sm': 'w-4 h-4',
    'md': 'w-5 h-5',
    'lg': 'w-6 h-6'
  }[size];
  
  // Get color class for text based on status
  const getStatusColorClass = () => {
    switch (status) {
      case 'Pit-in':
        return 'text-alarm';
      case 'Pit-out':
        return 'text-accent';
      case 'Finished':
        return 'text-info';
      case 'Stopped':
        return 'text-alarm';
      case 'Up':
        return 'text-live';
      case 'Down':
        return 'text-alarm';
      case 'On Track':
        return 'text-live';
      default:
        // Log unexpected status values for debugging
        console.warn(`Unexpected status value: "${status}"`);
        return 'text-muted';
    }
  };

  return (
    <div className="flex items-center gap-1">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img 
        src={imageUrl} 
        alt={status}
        className={`${sizeClass} object-contain`}
        onError={(e) => {
          // Fallback to a colored dot if image fails to load
          const target = e.target as HTMLImageElement;
          target.style.display = 'none';
        }}
      />
      <span className={`text-sm font-medium ${getStatusColorClass()}`}>
        {status}
      </span>
    </div>
  );
};

export default StatusImageIndicator;
