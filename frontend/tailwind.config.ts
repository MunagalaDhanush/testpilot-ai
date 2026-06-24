import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        bg: '#050508',
        surface: '#0d0d14',
        border: '#1a1a2e',
        cyan: {
          DEFAULT: '#00d4ff',
          dim: '#00a3c4',
        },
        violet: {
          DEFAULT: '#7c3aed',
          dim: '#5b21b6',
        },
        success: '#00ff88',
        warning: '#f59e0b',
        danger: '#ef4444',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      boxShadow: {
        'glow-cyan': '0 0 20px rgba(0, 212, 255, 0.25)',
        'glow-violet': '0 0 20px rgba(124, 58, 237, 0.25)',
        'glow-success': '0 0 20px rgba(0, 255, 136, 0.25)',
        'glow-danger': '0 0 20px rgba(239, 68, 68, 0.25)',
      },
      animation: {
        pulse_slow: 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
};

export default config;
