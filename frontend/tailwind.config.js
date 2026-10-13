/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          bg: '#ece9e2',
          surface: '#fcfbf8',
          surfaceAlt: '#fcfbf8',
          card: '#fcfbf8',
          cardSubtle: '#f5f4f0',
          cardHover: '#eeece7',
          border: '#e0ddd6',
          borderLight: '#eeece7',
          accent: '#ffc947',
          accentHover: '#f0b830',
          accentLight: '#fff8e6',
          accentText: '#8a6d00',
          text: '#262626',
          textMuted: '#7a7771',
          textSubtle: '#9a978f',
          dark: '#262626',
          success: '#4a7c59',
          warning: '#c75b39',
          error: '#b3402a',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Roboto',
          'Oxygen',
          'Ubuntu',
          'Cantarell',
          'sans-serif',
        ],
        mono: [
          'JetBrains Mono',
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Monaco',
          'Consolas',
          'monospace',
        ],
      },
      boxShadow: {
        subtle: '0 1px 2px 0 rgba(0, 0, 0, 0.03)',
        card: '0 1px 3px 0 rgba(0, 0, 0, 0.04), 0 1px 2px -1px rgba(0, 0, 0, 0.03)',
        cardHover: '0 4px 12px -2px rgba(255, 201, 71, 0.12), 0 2px 4px -1px rgba(0, 0, 0, 0.03)',
        drawer: '-4px 0 24px rgba(0, 0, 0, 0.08)',
        input: '0 2px 8px -2px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(0, 0, 0, 0.04)',
        inputFocus: '0 0 0 3px rgba(255, 201, 71, 0.25), 0 2px 8px -2px rgba(0, 0, 0, 0.06)',
      },
      borderRadius: {
        '2xl': '16px',
        'xl': '12px',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideInRight: {
          '0%': { transform: 'translateX(100%)' },
          '100%': { transform: 'translateX(0)' },
        },
        slideInUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
      },
      animation: {
        fadeIn: 'fadeIn 0.2s ease-out',
        slideInRight: 'slideInRight 0.25s ease-out',
        slideInUp: 'slideInUp 0.3s ease-out',
      },
    },
  },
  plugins: [],
}
