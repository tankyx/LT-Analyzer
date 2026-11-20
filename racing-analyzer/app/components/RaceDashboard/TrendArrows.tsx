import React from 'react';
import type { Trend } from './lib/gaps';

/** Up to three arrows showing how fast a gap is moving; green when it moves your way. */
const TrendArrows = ({ trend }: { trend: Trend | undefined }) => {
  if (!trend || trend.arrow === 0) {
    return <span className="text-muted">~</span>;
  }
  
  const getArrows = () => {
    const arrow = trend.value < 0 ? '↓' : '↑';
    return arrow.repeat(trend.arrow);
  };
  
  const getColor = () => {
    // Simplified logic based on trend direction
    return trend.value < 0 ? 'text-live' : 'text-alarm';
  };
  
  return (
    <span className={`font-bold ${getColor()}`}>
      {getArrows()}
    </span>
  );
};

export default TrendArrows;
