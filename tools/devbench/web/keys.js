// Keyboard from the browser to the ST, through the agent API (via the DevBench's /api/hatari proxy).
//
//   attachKeys(element, {joystick: () => bool, onError: fn})
//
// While the element has focus, key presses go to the ST as key down / key up
// (POST /input/key?action=down|up), so games see keys held for as long as you
// hold them. With joystick() true, the cursor keys and Space / Ctrl drive the
// joystick in port 1 instead (POST /input/joystick, latched until released).
(function () {
  const NAMES = {
    ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
    Enter: "return", Escape: "esc", Backspace: "backspace", Tab: "tab", " ": "space",
    Delete: "delete", Insert: "insert", Home: "home", Shift: "shift", Control: "ctrl",
    Alt: "alt", CapsLock: "capslock", PageUp: "help", PageDown: "undo",
  };
  for (let i = 1; i <= 10; i++) NAMES["F" + i] = "f" + i;
  const JOY = {ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right"};
  const FIRE = new Set([" ", "Control"]);

  function stKey(e) {
    if (NAMES[e.key]) return NAMES[e.key];
    if (e.code && e.code.startsWith("Numpad")) {
      const n = e.code.slice(6);
      const kp = {Enter: "kpenter", Add: "kp+", Subtract: "kp-", Multiply: "kp*", Divide: "kp/", Decimal: "kp."};
      if (/^\d$/.test(n)) return "kp" + n;
      if (kp[n]) return kp[n];
    }
    if (e.key.length === 1) return e.key.toLowerCase();
    return null;
  }

  function post(path, params) {
    const q = Object.entries(params).map(([k, v]) => encodeURIComponent(k) + "=" + encodeURIComponent(v)).join("&");
    return fetch("/api/hatari" + path + "?" + q, {method: "POST"}).then(r => {
      if (!r.ok) return r.json().then(d => { throw new Error(d.error || r.statusText); }, () => { throw new Error(r.statusText); });
    });
  }

  window.attachKeys = function (el, opts) {
    opts = opts || {};
    const joyMode = opts.joystick || (() => false);
    const onError = opts.onError || (() => {});
    let chain = Promise.resolve();       // keep downs and ups in order
    const send = (path, params) => { chain = chain.then(() => post(path, params)).catch(onError); };
    const held = new Set(), keysDown = new Set();
    let fire = false;
    const joy = () => send("/input/joystick", {port: 1, dirs: held.size ? [...held].join(",") : "none",
                                               fire: fire ? 1 : 0, frames: 0});
    el.addEventListener("keydown", (e) => {
      if (e.metaKey) return;              // leave browser shortcuts alone
      e.preventDefault();
      if (e.repeat) return;
      if (joyMode() && (JOY[e.key] || FIRE.has(e.key))) {
        if (JOY[e.key]) held.add(JOY[e.key]); else fire = true;
        return joy();
      }
      const k = stKey(e);
      if (k && !keysDown.has(k)) { keysDown.add(k); send("/input/key", {key: k, action: "down"}); }
    });
    el.addEventListener("keyup", (e) => {
      if (e.metaKey) return;
      e.preventDefault();
      if (JOY[e.key] && held.has(JOY[e.key])) { held.delete(JOY[e.key]); return joy(); }
      if (FIRE.has(e.key) && fire) { fire = false; return joy(); }
      const k = stKey(e);
      if (k && keysDown.has(k)) { keysDown.delete(k); send("/input/key", {key: k, action: "up"}); }
    });
    // let go of everything when focus leaves, so nothing stays held on the ST
    el.addEventListener("blur", () => {
      keysDown.forEach(k => send("/input/key", {key: k, action: "up"}));
      keysDown.clear();
      if (held.size || fire) { held.clear(); fire = false; joy(); }
    });
  };
})();
