import React from 'react';

interface ChaoticOrbitLoaderProps {
  size?: number;
  className?: string;
}

export const ChaoticOrbitLoader: React.FC<ChaoticOrbitLoaderProps> = ({
  size = 25,
  className = '',
}) => {
  return (
    <div
      className={`chaotic-orbit ${className}`}
      style={{ '--uib-size': `${size}px` } as React.CSSProperties}
      role="status"
      aria-label="Loading"
    />
  );
};

export default ChaoticOrbitLoader;
