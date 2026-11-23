/* Oil vs. Electrons: renders data/latest.json with Plotly. */
(async function () {
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const C = {
    oil: css("--s2"), oilEq: css("--s4"), ev: css("--s1"), chg: css("--s3"), alt: css("--s5"),
    mkt: css("--neutral"), text: css("--text"), text2: css("--text-2"), muted: css("--muted"),
    grid: css("--grid"), surface: css("--surface"), line: css("--line"),
  };
  const ENTITY = {
    "WTI crude": C.oil, USO: C.oil, "Oil & refining": C.oilEq, XLE: C.oilEq,
    "EV makers": C.ev, TSLA: C.ev, "EV charging": C.chg, CHPT: C.chg, EVGO: C.chg,
    NIO: C.alt, "S&P 500 (SPY)": C.mkt, SPY: C.mkt,
  };

  let d;
  try {
    d = await (await fetch("data/latest.json", { cache: "no-store" })).json();
  } catch (e) {
    document.getElementById("updated").textContent = "data failed to load";
    return;
  }

  // ------------------------------------------------------------ helpers
  const $ = (id) => document.getElementById(id);
  const pct = (x, n = 1) => (x == null ? "–" : (x * 100).toFixed(n) + "%");
  const sp = (x, n = 1) => (x == null ? "–" : (x >= 0 ? "+" : "") + (x * 100).toFixed(n) + "%");
  const num = (x, n = 2) => (x == null ? "–" : Number(x).toFixed(n));
  const usd = (x, n = 2) => (x == null ? "–" : (x < 0 ? "−$" : "$") + Math.abs(Number(x)).toFixed(n));
  const cents = (x) => (x == null ? "–" : (x * 100).toFixed(1) + "¢");
  const prob = (x) => (x == null ? "–" : x < 0.005 ? "<1%" : x > 0.995 ? ">99%" : (x * 100).toFixed(0) + "%");
  const cls = (x) => (x == null ? "" : x >= 0 ? "up" : "dn");
  const table = (el, head, rows) => {
    el.innerHTML = (head ? "<thead><tr>" + head.map((h) => `<th>${h}</th>`).join("") + "</tr></thead>" : "") +
      "<tbody>" + rows.join("") + "</tbody>";
  };
  const noteRow = (html, span) => `<tr><td class="note" colspan="${span}">${html}</td></tr>`;
  const tr = (cells, cl = "") => `<tr class="${cl}">` + cells.map((c) => `<td>${c}</td>`).join("") + "</tr>";
  const dot = (c) => `<span class="dot" style="background:${c}"></span>`;

  const baseLayout = (extra = {}) => ({
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Inter, -apple-system, Segoe UI, Roboto, sans-serif", size: 12, color: C.text2 },
    margin: { l: 52, r: 18, t: 34, b: 36 },
    hovermode: "x unified",
    hoverlabel: { bgcolor: C.surface, bordercolor: C.line, font: { color: C.text } },
    xaxis: { gridcolor: C.grid, linecolor: C.line, zeroline: false, tickfont: { color: C.muted } },
    yaxis: { gridcolor: C.grid, linecolor: C.line, zeroline: false, tickfont: { color: C.muted } },
    legend: { orientation: "h", x: 0, y: 1.01, yanchor: "bottom", font: { size: 11.5, color: C.text2 } },
    ...extra,
  });
  const cfg = { displayModeBar: false, responsive: true };
  const line = (s, name, color, extra = {}) => ({
    x: s.dates, y: s.values, name, type: "scatter", mode: "lines",
    line: { color, width: 2 }, ...extra,
  });
  const plot = (id, traces, layout) => { if ($(id)) Plotly.newPlot(id, traces, baseLayout(layout), cfg); };

  // --------------------------------------------------------------- meta
  if (d.meta.demo) $("demo-banner").hidden = false;
  $("updated").textContent = `Data as of ${d.meta.asof} · built ${d.meta.generated_at}`;
  const a = d.meta.assumptions;
  $("assumptions").innerHTML = [
    `Gasoline car: <b>${a.mpg} mpg</b> (typical new US car, real-world).`,
    `EV: <b>${a.kwh_per_mile} kWh/mile</b> including charging losses.`,
    `Home charging at the BLS US-average residential electricity price; public DC fast charging at <b>$${a.dcfc_price}/kWh</b> (typical US network list price).`,
    `Change these in <code>scripts/config.py</code>; every number on the page recomputes.`,
  ].map((x) => `<li>${x}</li>`).join("");
  if (d.meta.errors && d.meta.errors.length) $("errors").textContent = "Data notes from the last run: " + d.meta.errors.join(" · ");
  const repo = location.hostname.endsWith("github.io")
    ? `https://github.com/${location.hostname.split(".")[0]}/${location.pathname.split("/")[1]}` : "#";
  $("repo-link").href = repo;

  // ---------------------------------------------------------------- KPIs
  const k = d.kpis || {}, cm = d.curve?.metrics, ol = d.outlook, cpm = d.cpm, uso = (d.options || []).find((o) => o.ticker === "USO");
  const tiles = [];
  if (k["CL=F"]) tiles.push(["WTI crude", usd(k["CL=F"].last), `<span class="${cls(k["CL=F"].chg_1d)}">${sp(k["CL=F"].chg_1d)}</span> 1d · <span class="${cls(k["CL=F"].chg_1m)}">${sp(k["CL=F"].chg_1m)}</span> 1m`]);
  if (k["BZ=F"]) tiles.push(["Brent crude", usd(k["BZ=F"].last), `Brent–WTI ${usd(k.brent_wti)}`]);
  if (d.crack) tiles.push(["3-2-1 crack", usd(d.crack.current), `${num(d.crack.pctile_3y, 0)}th pctile (3y)`]);
  if (cm) tiles.push(["WTI M1 → M12", sp(cm.m1_m12_pct), cm.structure]);
  if (uso) tiles.push(["Oil implied vol (30d)", pct(uso.iv30), `±${pct(uso.move_1m)} 1-month move`]);
  if (cpm) tiles.push(["Gas vs EV, per mile", `${cents(cpm.current.gas)} / ${cents(cpm.current.home)}`, `gasoline / home charging`]);
  if (ol && ol.prob_dcfc_cheaper_12m != null) tiles.push(["P(fast-charging < gas, 12m)", prob(ol.prob_dcfc_cheaper_12m), `breakeven WTI ${usd(cpm.breakeven.wti_vs_dcfc, 0)}`]);
  $("kpis").innerHTML = tiles.map(([l, v, s]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="d">${s}</div></div>`).join("");

  $("commentary").innerHTML = (d.commentary || []).map((x) => `<li>${x}</li>`).join("");
  $("watch").innerHTML = (d.watch || []).map((x) => `<li>${x}</li>`).join("");

  // ---------------------------------------------------------- 1. curve
  const MON = { Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5, Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11 };
  const lblDate = (l) => { const [m, y] = l.split(" "); return `20${y}-${String(MON[m] + 1).padStart(2, "0")}-01`; };
  if (d.curve) {
    const cur = d.curve.current;
    const traces = [];
    const snapCol = [C.muted, C.mkt, C.grid];
    Object.entries(d.history?.curve_snapshots || {}).forEach(([lbl, s], i) => {
      traces.push({ x: s.points.map((p) => lblDate(p.label)), y: s.points.map((p) => p.price), name: `${lbl} (${s.date})`,
        type: "scatter", mode: "lines", line: { color: C.muted, width: 1.5, dash: ["dot", "dash", "longdash"][i] } });
    });
    traces.push({ x: cur.map((p) => lblDate(p.label)), y: cur.map((p) => p.price), name: `Today (${d.meta.asof})`, type: "scatter",
      mode: "lines+markers", line: { color: C.oil, width: 2.5 }, marker: { size: 7, color: C.oil, line: { color: C.surface, width: 2 } },
      hovertemplate: "%{x|%b %Y}: $%{y:.2f}<extra></extra>" });
    plot("ch-curve", traces, { hovermode: "closest", yaxis: { ...baseLayout().yaxis, tickprefix: "$" }, xaxis: { ...baseLayout().xaxis, type: "date", tickformat: "%b %y", title: { text: "delivery month", font: { size: 11 } } } });

    table($("tb-curve"), null, [
      tr(["Front month (M1)", usd(cm.m1)]), tr(["M1 − M2", usd(cm.m1_m2)]), tr(["M1 − M7 (6 months)", usd(cm.m1_m7)]),
      tr(["M1 − M12", usd(cm.m1_m12)]), tr(["Shape", `<b>${cm.structure}</b>`]),
      tr(["Annualised roll yield (M1→M12)", sp(cm.roll_yield_ann)]),
      tr(["Risk-free r (3M T-bill, cont.)", pct(cm.rf, 2)]),
      tr(["Implied net convenience yield (y − u)", sp(cm.conv_yield_net)]),
      tr(["Collateralised long-futures carry (r + roll)", sp(cm.rf + cm.roll_yield_ann)]),
    ]);
  }

  if (d.crack) {
    plot("ch-crack", [
      line(d.crack.series, "3-2-1 crack", C.oil, { hovertemplate: "$%{y:.2f}<extra>3-2-1</extra>" }),
      { x: [d.crack.series.dates[0], d.crack.series.dates.at(-1)], y: [d.crack.avg_1y, d.crack.avg_1y], name: "1-year average",
        mode: "lines", line: { color: C.muted, width: 1, dash: "dot" }, hoverinfo: "skip" },
    ], { yaxis: { ...baseLayout().yaxis, tickprefix: "$" } });
  }
  if (d.retail) {
    plot("ch-retail", [
      line(d.retail.retail, "Retail regular (EIA)", C.oil, { hovertemplate: "$%{y:.3f}" }),
      line(d.retail.rbob, "RBOB wholesale (weekly avg)", C.oilEq, { hovertemplate: "$%{y:.3f}" }),
    ], { yaxis: { ...baseLayout().yaxis, tickprefix: "$" } });
  }

  // ------------------------------------------------------- 2. per mile
  if (cpm) {
    $("cpm-sub").textContent = `Gasoline at EIA weekly retail ÷ ${a.mpg} mpg; EV at ${a.kwh_per_mile} kWh/mile × electricity price`;
    const g = cpm.gas_hist;
    plot("ch-cpm", [
      line(g, "Gasoline car", C.oil, { hovertemplate: "%{y:.3f} $/mi" }),
      line(cpm.home_hist, "EV, home charging", C.ev, { line: { color: C.ev, width: 2, shape: "hv" }, hovertemplate: "%{y:.3f} $/mi" }),
      { x: [g.dates[0], g.dates.at(-1)], y: [cpm.current.dcfc, cpm.current.dcfc], name: "EV, public fast charging (assumed)",
        mode: "lines", line: { color: C.chg, width: 2, dash: "dash" }, hovertemplate: "%{y:.3f} $/mi" },
    ], { yaxis: { ...baseLayout().yaxis, tickformat: "$.2f", rangemode: "tozero" } });
    const be = cpm.breakeven, pt = d.retail;
    table($("tb-be"), ["", "Gasoline $/gal", "≈ WTI $/bbl"], [
      tr([`${dot(C.chg)}EV fast charging = gasoline`, usd(be.gas_vs_dcfc), usd(be.wti_vs_dcfc, 0)]),
      tr([`${dot(C.ev)}EV home charging = gasoline`, usd(be.gas_vs_home), be.wti_vs_home > 0 ? usd(be.wti_vs_home, 0) : "below any realistic price"]),
      tr(["Today", usd(pt?.gas_last), usd(k["CL=F"]?.last, 0)]),
      tr(["Saving per 10,000 miles, home charging", "", `$${Math.round(cpm.ev_saving_per_10k_home).toLocaleString()}`]),
      tr(["Saving per 10,000 miles, fast charging", "", `${cpm.ev_saving_per_10k_dcfc < 0 ? "−" : ""}$${Math.abs(Math.round(cpm.ev_saving_per_10k_dcfc)).toLocaleString()}`]),
      pt ? noteRow(`Pass-through: pump = ${num(pt.a, 2)} + ${num(pt.b, 4)} × WTI (R² ${num(pt.r2, 2)}, n=${pt.n}), so each $1/bbl adds ~${num(pt.cents_per_dollar, 1)}¢/gal. Electricity ${usd(cpm.current.elec_price, 3)}/kWh (${cpm.current.elec_asof}).`, 3) : "",
    ]);
  }

  // -------------------------------------------------------- 3. outlook
  if (ol) {
    const P = ol.path, m = P.map((r) => r.month);
    const band = (lo, hi, name, op) => [
      { x: m, y: P.map((r) => r[hi]), mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
      { x: m, y: P.map((r) => r[lo]), mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: hexA(C.oil, op), name, hoverinfo: "skip" },
    ];
    const tr_ = [
      ...band("p05", "p95", "90% range", 0.15), ...band("p25", "p75", "50% range", 0.28),
      { x: m, y: P.map((r) => r.fwd), name: "Futures price", mode: "lines+markers", line: { color: C.oil, width: 2.5 },
        marker: { size: 6, color: C.oil }, customdata: P.map((r) => [r.p05, r.p95, r.sigma]),
        hovertemplate: "Futures $%{y:.2f}<br>90%: $%{customdata[0]:.0f}–$%{customdata[1]:.0f}<br>σ %{customdata[2]:.0%}<extra></extra>" },
    ];
    const shapes = [], ann = [];
    if (cpm?.breakeven?.wti_vs_dcfc) {
      const y = cpm.breakeven.wti_vs_dcfc;
      shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y, line: { color: C.chg, width: 1.5, dash: "dash" } });
      ann.push({ xref: "paper", x: 0.01, y, yanchor: "bottom", xanchor: "left", text: `Fast-charging breakeven ≈ $${y.toFixed(0)}`, showarrow: false, font: { size: 11, color: C.text2 } });
    }
    plot("ch-fan", tr_, { xaxis: { ...baseLayout().xaxis, type: "category" }, yaxis: { ...baseLayout().yaxis, tickprefix: "$" }, shapes, annotations: ann });

    if (ol.gas_path) {
      const G = ol.gas_path, gm = G.map((r) => r.month);
      plot("ch-fan-cpm", [
        { x: gm, y: G.map((r) => r.p95), mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
        { x: gm, y: G.map((r) => r.p05), mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: hexA(C.oil, 0.18), name: "Gasoline, 90% range", hoverinfo: "skip" },
        { x: gm, y: G.map((r) => r.fwd), name: "Gasoline (futures-implied)", mode: "lines", line: { color: C.oil, width: 2.5 }, hovertemplate: "%{y:.3f} $/mi" },
        { x: gm, y: gm.map(() => cpm.current.home), name: "EV, home", mode: "lines", line: { color: C.ev, width: 2 }, hovertemplate: "%{y:.3f} $/mi" },
        { x: gm, y: gm.map(() => cpm.current.dcfc), name: "EV, fast charging", mode: "lines", line: { color: C.chg, width: 2, dash: "dash" }, hovertemplate: "%{y:.3f} $/mi" },
      ], { xaxis: { ...baseLayout().xaxis, type: "category" }, yaxis: { ...baseLayout().yaxis, tickformat: "$.2f", rangemode: "tozero" } });
    }
    table($("tb-prob"), ["Event by " + P.at(-1).month, "Risk-neutral probability", "Reading"], [
      tr(["WTI up more than 20%", prob(ol.prob_up20), `<span class="note">above $${(ol.spot * 1.2).toFixed(0)}</span>`]),
      tr(["WTI down more than 20%", prob(ol.prob_down20), `<span class="note">below $${(ol.spot * 0.8).toFixed(0)}</span>`]),
      tr(["WTI above $100", prob(ol.prob_above_100), `<span class="note">a supply-shock scenario</span>`]),
      tr(["WTI below $50", prob(ol.prob_below_50), `<span class="note">a demand-shock / oversupply scenario</span>`]),
      ol.prob_dcfc_cheaper_12m != null ? tr(["Public fast charging cheaper per mile than gasoline", `<b>${prob(ol.prob_dcfc_cheaper_12m)}</b>`, `<span class="note">WTI above ≈$${cpm.breakeven.wti_vs_dcfc.toFixed(0)}</span>`]) : "",
      noteRow(`Futures 12m: $${ol.f12} · 12m implied vol ${pct(ol.sigma12, 0)} · spot $${ol.spot}. Risk-neutral probabilities include risk premia; treat them as the market's price of each scenario, not a forecast.`, 3),
    ]);
  }

  // ------------------------------------------------------- 4. equities
  const eq = d.equities;
  if (eq) {
    const drawPerf = (days) => {
      const tr_ = Object.entries(eq.perf).map(([name, s]) => {
        const n = s.dates.length, i0 = Math.max(0, n - days), base = s.values[i0];
        return { x: s.dates.slice(i0), y: s.values.slice(i0).map((v) => (100 * v) / base), name, type: "scatter", mode: "lines",
          line: { color: ENTITY[name] || C.mkt, width: name.startsWith("S&P") ? 1.5 : 2, dash: name.startsWith("S&P") ? "dot" : "solid" },
          hovertemplate: "%{y:.1f}" };
      });
      plot("ch-perf", tr_, {});
    };
    drawPerf(252);
    document.querySelectorAll("#perf-range button").forEach((b) => b.addEventListener("click", () => {
      document.querySelectorAll("#perf-range button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on"); drawPerf(+b.dataset.d);
    }));

    plot("ch-rbeta", Object.entries(eq.rolling_oil_beta).map(([g, s]) => line(s, g, ENTITY[g], { hovertemplate: "%{y:.2f}" })),
      { shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: C.muted, width: 1 } }] });

    const rows = [];
    const bf = Object.fromEntries((eq.basket_factor || []).map((b) => [b.group, b]));
    const fmtRow = (name, f, bold) => tr([
      bold ? `${dot(ENTITY[name])}<b>${name} basket</b>` : name, num(f.beta_mkt), `<span class="${Math.abs(f.t_oil) > 2 ? "sig" : ""}">${num(f.beta_oil)}</span>`,
      num(f.t_oil, 1), num(f.r2), pct(f.idio_vol, 0), sp(f.ret_1y, 0)]);
    Object.keys(eq.rolling_oil_beta).forEach((g) => {
      if (bf[g]) rows.push(fmtRow(g, bf[g], true));
      eq.factor.filter((f) => f.group === g).forEach((f) => rows.push(fmtRow(f.ticker, f, false)));
    });
    table($("tb-factor"), ["", "β market", "β oil", "t(β oil)", "R²", "Idio. vol", "1y return"], rows);

    if (eq.transition_spread) {
      const tf = eq.transition_factor;
      $("spread-sub").innerHTML = tf ? `Cumulative, rebased to 100. Over the last year the spread had β<sub>mkt</sub> ${num(tf.beta_mkt)} and β<sub>oil</sub> ${num(tf.beta_oil)} (t=${num(tf.t_oil, 1)}): ${tf.beta_oil < 0 ? "it does pay off when oil falls" : "it is not a clean bet against oil"}, ${tf.beta_mkt > 0.5 ? "and it is mostly a leveraged bet on the equity market." : "and it is fairly market-neutral."}` : "";
      plot("ch-spread", [line(eq.transition_spread, "EV makers ÷ oil & refining", C.ev, { fill: "none", hovertemplate: "%{y:.1f}" })],
        { showlegend: false, shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 100, y1: 100, line: { color: C.muted, width: 1 } }] });
    }
  }

  // ---------------------------------------------------- 5. options/vol
  const opts = d.options || [];
  if (opts.length) {
    plot("ch-term", opts.map((o) => ({
      x: o.term.map((t) => t.days), y: o.term.map((t) => t.iv), name: o.ticker, mode: "lines+markers", type: "scatter",
      line: { color: ENTITY[o.ticker], width: 2 }, marker: { size: 7, color: ENTITY[o.ticker], line: { color: C.surface, width: 2 } },
      customdata: o.term.map((t) => t.expiry), hovertemplate: o.ticker + " %{customdata}: %{y:.1%}<extra></extra>",
    })), { hovermode: "closest", xaxis: { ...baseLayout().xaxis, title: { text: "days to expiry", font: { size: 11 } } }, yaxis: { ...baseLayout().yaxis, tickformat: ".0%" } });

    plot("ch-smile", opts.map((o) => ({
      x: o.smile.m, y: o.smile.iv, name: `${o.ticker} (${o.smile.days}d)`, mode: "lines+markers", type: "scatter",
      line: { color: ENTITY[o.ticker], width: 2 }, marker: { size: 5, color: ENTITY[o.ticker] }, hovertemplate: "K/F %{x:.2f}: %{y:.1%}",
    })), { hovermode: "closest", xaxis: { ...baseLayout().xaxis, title: { text: "moneyness K / F", font: { size: 11 } } }, yaxis: { ...baseLayout().yaxis, tickformat: ".0%" },
      shapes: [{ type: "line", x0: 1, x1: 1, yref: "paper", y0: 0, y1: 1, line: { color: C.muted, width: 1, dash: "dot" } }] });

    table($("tb-greeks"), ["", "Spot", "IV 30d", "RV 20d", "IV − RV", "90/110 skew", "±1m move", "ATM call", "Δ call", "Γ", "Vega /1pt", "Θ call /day"],
      opts.map((o) => tr([`${dot(ENTITY[o.ticker])}${o.label}`, usd(o.spot), pct(o.iv30), pct(o.rv20),
        `<span class="${cls(o.vrp)}">${o.vrp == null ? "–" : (o.vrp * 100 >= 0 ? "+" : "") + (o.vrp * 100).toFixed(1) + " pts"}</span>`,
        o.skew_90_110 == null ? "–" : (o.skew_90_110 * 100).toFixed(1) + " pts", pct(o.move_1m),
        usd(o.greeks.call_price), num(o.greeks.call_delta, 3), num(o.greeks.gamma, 4), usd(o.greeks.vega_1pt, 3), usd(o.greeks.call_theta_day, 3)])));
  }
  if (d.vol) {
    plot("ch-rv", Object.entries(d.vol.rv60).map(([n, s]) => line(s, n, ENTITY[n] || C.mkt, { hovertemplate: "%{y:.1%}", line: { color: ENTITY[n] || C.mkt, width: n === "SPY" ? 1.5 : 2, dash: n === "SPY" ? "dot" : "solid" } })),
      { yaxis: { ...baseLayout().yaxis, tickformat: ".0%", rangemode: "tozero" } });
  }
  if (d.risk) {
    table($("tb-var"), ["", "Hist. VaR", "Hist. ES", "EWMA σ (1d)", "Param. VaR"],
      d.risk.map((r) => tr([`${dot(ENTITY[r.name] || C.mkt)}${r.name}`, pct(r.hist_var, 2), pct(r.hist_es, 2), pct(r.ewma_vol_daily, 2), pct(r.param_var, 2)])));
  }

  // -------------------------------------------------------- 6. log
  const H = d.history?.metrics;
  if (H && H.date) {
    const n = H.date.length;
    $("log-sub").textContent = n < 2
      ? `The tracking log started on ${H.date[0]}. Each trading day the pipeline appends a row (front-month WTI, the 12-month futures price, implied vols, cost per mile, the fast-charging probability), and these charts fill in.`
      : `${n} trading days logged since ${H.date[0]}. Each run appends a row to data/metrics_history.csv in the repo.`;
    const mk = (key, name, color, fmt) => ({ x: H.date, y: H[key], name, mode: n < 30 ? "lines+markers" : "lines", line: { color, width: 2 }, marker: { size: 7, color }, hovertemplate: fmt });
    if (n < 3) { $("ch-log1").parentElement.hidden = true; return; }
    plot("ch-log1", [mk("wti", "WTI front", C.oil, "$%{y:.2f}"), mk("wti_f12", "WTI 12m futures", C.oilEq, "$%{y:.2f}")], { yaxis: { ...baseLayout().yaxis, tickprefix: "$" } });
    plot("ch-log2", [mk("uso_iv30", "USO IV 30d", C.oil, "%{y:.1%}"), mk("tsla_iv30", "TSLA IV 30d", C.ev, "%{y:.1%}")], { yaxis: { ...baseLayout().yaxis, tickformat: ".0%" } });
  }

  function hexA(hex, a) {
    const h = hex.replace("#", "");
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
    return `rgba(${r},${g},${b},${a})`;
  }
})();
