// Runs before first paint so a saved theme never flashes the other one.
(function () {
  try {
    var t = localStorage.getItem("rl-theme");
    if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
  } catch (e) { /* storage blocked: follow the OS */ }
})();
