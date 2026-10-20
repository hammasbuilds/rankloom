/* The page around one animation: fits it to the window, and gives it
   play/pause, restart and a chip per step to jump to. */
(function () {
  const spec = JSON.parse(document.getElementById("spec").textContent);
  document.title = spec.title + " - " + (spec.repo || "");
  const app = document.getElementById("app");
  const player = ISO.mount(spec, app);
  window.PLAYER = player;

  const bar = document.createElement("div");
  bar.className = "iso-bar";
  bar.innerHTML = `<button data-act="play" aria-label="Pause">❚❚</button>
    <button data-act="restart" aria-label="From the start">⟲</button>
    <input type="range" min="0" max="${player.total.toFixed(2)}" step="0.01"
      value="0" aria-label="Time">
    <span class="iso-steps">${player.steps.map((s, i) => `<button
      data-step="${i}" title="${s.title.replace(/"/g, "&quot;")}">${i + 1}
      </button>`).join("")}</span>
    <a href="../index.html" class="iso-back">All animations</a>`;
  document.body.append(bar);
  const play = bar.querySelector('[data-act="play"]');
  const range = bar.querySelector('input[type="range"]');
  const sync = () => {
    play.textContent = player.playing ? "❚❚" : "▶";
    play.setAttribute("aria-label", player.playing ? "Pause" : "Play");
  };
  play.addEventListener("click", () => {
    player.playing ? player.pause() : player.play();
    sync();
  });
  bar.querySelector('[data-act="restart"]').addEventListener("click", () => {
    player.seek(0); if (!player.playing) player.play(); sync();
  });
  range.addEventListener("input", () => {
    player.pause(); player.seek(Number(range.value)); sync();
  });
  bar.querySelectorAll("[data-step]").forEach((b) => b.addEventListener(
    "click", () => {
      const s = player.steps[Number(b.dataset.step)];
      player.pause(); player.seek(s.start + s.travel + 0.6); sync();
    }));
  player.ontick = (t) => { range.value = t; };
  document.addEventListener("keydown", (ev) => {
    if (ev.key === " ") { ev.preventDefault(); play.click(); }
  });

  /* fit the 1080x1350 stage into whatever window it is in */
  const fit = () => {
    const s = Math.min((innerWidth - 24) / ISO.W, (innerHeight - 70) / ISO.H);
    app.style.setProperty("--s", String(Math.max(0.2, s)));
  };
  addEventListener("resize", fit);
  fit();
  sync();
})();
