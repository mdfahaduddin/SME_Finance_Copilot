// Apply the saved theme before first paint to avoid a flash.
// Kept as a file (not inline) so the Content-Security-Policy can forbid inline scripts.
try {
  const t = localStorage.getItem("theme");
  if (t === "dark" || (!t && matchMedia("(prefers-color-scheme: dark)").matches)) {
    document.documentElement.classList.add("dark");
  }
} catch {}
