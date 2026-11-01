// Display units. config.yaml and the API are always metric; pages convert at the edges.
// The choice is config `ui.units` ("metric" | "imperial") so every page and device agrees.
const FT = 0.3048;

const Units = {
  system: 'metric',
  set(system) { this.system = system === 'imperial' ? 'imperial' : 'metric'; },
  fromConfig(cfg) { this.set(cfg?.ui?.units); },
  get imperial() { return this.system === 'imperial'; },
  get unit() { return this.imperial ? 'ft' : 'm'; },

  toDisplay(m) { return this.imperial ? m / FT : m; },
  fromDisplay(v) { return this.imperial ? v * FT : v; },
  // value for an <input>: trimmed, no trailing zeros
  input(m, digits = 2) { return String(+this.toDisplay(m).toFixed(digits)); },

  len(m, digits = 1) { return m == null ? '—' : `${this.toDisplay(m).toFixed(digits)} ${this.unit}`; },
  xy(x, y, digits = 1) { return `(${this.toDisplay(x).toFixed(digits)}, ${this.toDisplay(y).toFixed(digits)}) ${this.unit}`; },
  // a person-sized height: 1.64 m / 5′ 5″
  height(m) {
    if (m == null) return '—';
    if (!this.imperial) return `${m.toFixed(2)} m`;
    let inches = Math.round(m / 0.0254), ft = Math.floor(inches / 12);
    return `${ft}′ ${inches - ft * 12}″`;
  },

  // Typed length -> metres (NaN if unreadable). A bare number is in the current unit; also
  // takes 5'9", 5' 9, 5ft 9in, 69in, 1.75m, 175cm.
  parse(text) {
    const s = String(text).trim().toLowerCase().replace(/[′’]/g, "'").replace(/[″”]/g, '"');
    if (!s) return NaN;
    let m = s.match(/^(-?\d+(?:\.\d+)?)\s*(?:'|ft|feet|foot)\s*(?:(\d+(?:\.\d+)?)\s*(?:"|in|inch|inches)?)?$/);
    if (m) return (parseFloat(m[1]) * 12 + (m[2] ? parseFloat(m[2]) : 0) * Math.sign(parseFloat(m[1]) || 1)) * 0.0254;
    if ((m = s.match(/^(-?\d+(?:\.\d+)?)\s*(?:"|in|inch|inches)$/))) return parseFloat(m[1]) * 0.0254;
    if ((m = s.match(/^(-?\d+(?:\.\d+)?)\s*cm$/))) return parseFloat(m[1]) / 100;
    if ((m = s.match(/^(-?\d+(?:\.\d+)?)\s*m$/))) return parseFloat(m[1]);
    if (/^-?\d+(?:\.\d+)?$/.test(s) || /^-?\.\d+$/.test(s)) return this.fromDisplay(parseFloat(s));
    return NaN;
  },

  // A small "m | ft" switch that saves the choice for everyone and calls onChange.
  toggle(onChange) {
    const el = document.createElement('span');
    el.className = 'units-toggle';
    el.title = 'Units for distances and heights (the config stays in metres)';
    el.innerHTML = '<button data-u="metric">m</button><button data-u="imperial">ft</button>';
    const paint = () => el.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.u === this.system));
    el.querySelectorAll('button').forEach(b => b.onclick = async () => {
      if (b.dataset.u === this.system) return;
      this.set(b.dataset.u);
      paint();
      await fetch('/api/settings/save', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ui: {units: this.system}})}).catch(() => {});
      onChange?.();
    });
    paint();
    return el;
  },
};
const UNITS_CSS = `.units-toggle { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
  .units-toggle button { border: 0; border-radius: 0; padding: 4px 10px; background: transparent; color: var(--text);
    font: inherit; font-size: 14px; cursor: pointer; }
  .units-toggle button.on { background: var(--accent); color: #fff; }`;
document.head.appendChild(Object.assign(document.createElement('style'), {textContent: UNITS_CSS}));
