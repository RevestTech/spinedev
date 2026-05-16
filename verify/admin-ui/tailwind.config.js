/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        sidebar: "#1a1a2e",
        content: "#f5f5f7",
        accent: "#3b82f6",
      },
    },
  },
  plugins: [],
}
