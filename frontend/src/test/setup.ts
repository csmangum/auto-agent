import '@testing-library/jest-dom';

// Stub ResizeObserver for Recharts (not provided by jsdom)
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};
