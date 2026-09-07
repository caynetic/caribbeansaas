module.exports = {
  content: ["./*.html", "./scripts/directory_catalog.py"],
  theme: {
    extend: {
      colors: {
        primary: "#F4F7F8", secondary: "#8FA1AA", background: "#0B0F12",
        surface: "#12181D", outline: "#25313A", sea: "#00C2D7",
        reef: "#2ED6A3", lagoon: "#7FE7F2", sunset: "#FF7A59"
      },
      fontFamily: { sans: ["Geist", "ui-sans-serif", "system-ui", "sans-serif"] },
      boxShadow: { spectral: "0 28px 100px rgba(0, 0, 0, 0.42)" }
    }
  },
  plugins: [require("@tailwindcss/forms"), require("@tailwindcss/container-queries")]
};
