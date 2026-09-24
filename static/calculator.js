/* On-screen calculator for Data Insights (and timed practice of DI topics).
   Safe expression evaluation via shunting-yard — no eval(). */
(function () {
  const buttons = [
    ["C", "clear"], ["(", "op"], [")", "op"], ["⌫", "back"],
    ["7", ""], ["8", ""], ["9", ""], ["/", "op"],
    ["4", ""], ["5", ""], ["6", ""], ["*", "op"],
    ["1", ""], ["2", ""], ["3", ""], ["-", "op"],
    ["0", ""], [".", ""], ["%", "op"], ["+", "op"],
    ["=", "eq"],
  ];

  let expr = "";

  function render() {
    const el = document.getElementById("calculator");
    if (!el) return;
    el.innerHTML =
      '<div class="calc-display" id="calc-display">0</div><div class="calc-grid"></div>';
    const grid = el.querySelector(".calc-grid");
    for (const [label, cls] of buttons) {
      const b = document.createElement("button");
      b.textContent = label;
      if (cls) b.className = cls;
      if (label === "=") b.style.gridColumn = "span 4";
      b.onclick = () => press(label);
      grid.appendChild(b);
    }
    updateDisplay();
  }

  function updateDisplay(val) {
    const d = document.getElementById("calc-display");
    if (d) d.textContent = val !== undefined ? val : (expr || "0");
  }

  function press(label) {
    if (label === "C") { expr = ""; updateDisplay(); return; }
    if (label === "⌫") { expr = expr.slice(0, -1); updateDisplay(); return; }
    if (label === "=") {
      try {
        const result = evaluate(expr);
        updateDisplay(String(result));
        expr = String(result);
      } catch (e) {
        updateDisplay("Error");
        expr = "";
      }
      return;
    }
    expr += label;
    updateDisplay();
  }

  // ── Shunting-yard evaluator ──────────────────────────────
  function evaluate(input) {
    const tokens = tokenize(input);
    const output = [], ops = [];
    const prec = { "+": 1, "-": 1, "*": 2, "/": 2 };
    for (const t of tokens) {
      if (typeof t === "number") {
        output.push(t);
      } else if (t === "(") {
        ops.push(t);
      } else if (t === ")") {
        while (ops.length && ops[ops.length - 1] !== "(") output.push(ops.pop());
        ops.pop();
      } else {
        while (ops.length && prec[ops[ops.length - 1]] >= prec[t]) output.push(ops.pop());
        ops.push(t);
      }
    }
    while (ops.length) output.push(ops.pop());

    const st = [];
    for (const t of output) {
      if (typeof t === "number") { st.push(t); continue; }
      const b = st.pop(), a = st.pop();
      if (a === undefined || b === undefined) throw new Error("bad expr");
      st.push(t === "+" ? a + b : t === "-" ? a - b : t === "*" ? a * b : a / b);
    }
    if (st.length !== 1 || !isFinite(st[0])) throw new Error("bad expr");
    return Math.round(st[0] * 1e10) / 1e10;
  }

  function tokenize(s) {
    const out = [];
    let i = 0;
    while (i < s.length) {
      const c = s[i];
      if (c === " ") { i++; continue; }
      if ("+-*/()".includes(c)) { out.push(c); i++; continue; }
      if (c === "%") { // treat X% as X/100
        out.push("/"); out.push(100); i++; continue;
      }
      if (/[0-9.]/.test(c)) {
        let num = "";
        while (i < s.length && /[0-9.]/.test(s[i])) num += s[i++];
        out.push(parseFloat(num));
        continue;
      }
      throw new Error("bad char");
    }
    return out;
  }

  window.Calculator = { render };
})();
