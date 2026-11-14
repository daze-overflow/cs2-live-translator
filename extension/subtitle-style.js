(() => {
  const defaults = Object.freeze({ fontSize: 24, bottom: 22, width: 80,
    backgroundOpacity: 100, textOpacity: 100, align: "center", showEnglish: true });
  const bounds = { fontSize: [16, 48], bottom: [0, 60], width: [50, 96],
    backgroundOpacity: [0, 100], textOpacity: [0, 100] };
  function normalize(value = {}) {
    const input = value && typeof value === "object" ? value : {};
    const settings = { ...defaults };
    for (const [key, [min, max]] of Object.entries(bounds)) {
      if (typeof input[key] === "number" && Number.isFinite(input[key])) {
        settings[key] = Math.round(Math.min(max, Math.max(min, input[key])));
      }
    }
    if (["left", "center", "right"].includes(input.align)) settings.align = input.align;
    if (typeof input.showEnglish === "boolean") settings.showEnglish = input.showEnglish;
    return settings;
  }
  function apply(element, value) {
    const settings = normalize(value);
    const properties = { "--font-size": `${settings.fontSize}px`, "--caption-bottom": `${settings.bottom}%`,
      "--caption-width": `${settings.width}%`, "--background-alpha": String(settings.backgroundOpacity / 100),
      "--text-alpha": String(settings.textOpacity / 100) };
    for (const [key, value] of Object.entries(properties)) element.style.setProperty(key, value);
    element.dataset.align = settings.align;
    element.classList.toggle("hide-english", !settings.showEnglish);
    return settings;
  }
  globalThis.CS2SubtitleStyle = { defaults, normalize, apply };
})();
