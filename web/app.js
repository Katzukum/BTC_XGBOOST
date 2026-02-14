const fmtUsd = (n) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n || 0);
const fmtUsdCents = (n) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n || 0);
const fmtPct = (n) => `${(n || 0).toFixed(2)}%`;

let pnlChartInstance = null;
let btcChartInstance = null;
let currentTimeframe = "1m";

// --- Header & Metrics Rendering ---

function colorClass(val) {
  if (val > 0) return 'green';
  if (val < 0) return 'red';
  return '';
}

function renderHeader(h) {
  document.getElementById('headerPrice').innerText = fmtUsdCents(h.price);

  const pnlEl = document.getElementById('headerPnl');
  pnlEl.innerText = fmtUsd(h.total_pnl);
  pnlEl.className = `bold ${colorClass(h.total_pnl)}`;

  const dailyEl = document.getElementById('headerDaily');
  dailyEl.innerText = fmtUsd(h.daily_pnl);
  dailyEl.className = `bold ${colorClass(h.daily_pnl)}`;

  document.getElementById('headerWin').innerText = `${h.win_rate}%`;
  document.getElementById('headerTrades').innerText = h.total_trades;
  document.getElementById('headerOpen').innerText = fmtUsd(h.open_exposure);
  document.getElementById('headerNextWindow').innerText = `${Math.floor(h.next_window_seconds / 60)}:${String(h.next_window_seconds % 60).padStart(2, '0')}`;
  document.getElementById('headerSession').innerText = h.market_session;
}

function renderPnlSection(p) {
  document.getElementById('pnlBig').innerText = fmtUsd(p.total);

  const subHtml = `<span class="${colorClass(p.avg_trade)}">${fmtUsd(p.avg_trade)} avg</span> <span class="muted">·</span> ${p.return_pct}%`;
  document.getElementById('pnlSub').innerHTML = subHtml;

  const metricsHtml = [
    ['AVG / TRADE', fmtUsd(p.avg_trade), colorClass(p.avg_trade)],
    ['SHARPE', p.sharpe, ''],
    ['MAX DD', fmtUsd(p.max_dd), 'red'],
    ['OPEN POS', fmtUsd(p.total), 'yellow'],
    ['KELLY F*', `${p.kelly_f}%`, ''],
    ['DD LIMIT', `${p.dd_limit}%`, 'red']
  ].map(([label, val, cls]) => `
        <div class="metric-item">
            <h4>${label}</h4>
            <div class="value ${cls}">${val}</div>
        </div>
    `).join('');

  document.getElementById('metricsGrid').innerHTML = metricsHtml;
}

function renderOrderFeed(feed) {
  const rows = feed.map(o => `
        <tr>
            <td>${o.time}</td>
            <td>${o.window}</td>
            <td class="${o.side === 'UP' ? 'green' : 'red'}">${o.side}</td>
            <td>${o.entry}¢</td>
            <td>${fmtUsd(o.size)}</td>
        </tr>
    `).join('');
  document.getElementById('orderTableBody').innerHTML = rows;
}

function renderPipeline(p) {
  // pm_odds is now an array of objects: [{source, prob_up, time}, ...]
  let oddsHtml = '';
  if (Array.isArray(p.pm_odds) && p.pm_odds.length > 0) {
    oddsHtml = p.pm_odds.map(odd => {
      const prob = (odd.prob_up * 100).toFixed(1);
      const colorClass = odd.prob_up > 0.6 ? 'green' : (odd.prob_up < 0.4 ? 'red' : '');
      return `<div class="pipe-row" style="margin-bottom: 2px;">
                    <span class="muted" style="font-size: 10px; width: 40px; display: inline-block;">${odd.source.substring(0, 3)}</span> 
                    <span class="${colorClass}">${prob}% UP</span>
                  </div>`;
    }).join('');
  } else {
    oddsHtml = `<div class="pipe-row"><span>--</span></div>`;
  }

  // Render CEX FEEDS
  let feedsHtml = '';
  if (p.cex_feeds) {
    feedsHtml = p.cex_feeds.split(',').map(feed =>
      `<div class="pipe-row" style="margin-bottom: 2px;">
         <span style="font-size: 10px;">${feed.trim()}</span>
       </div>`
    ).join('');
  }

  const steps = [
    { title: '01 CEX FEEDS', content: feedsHtml },
    { title: '02 MODEL ODDS', content: oddsHtml },
    {
      title: '03 EDGE', content: (() => {
        if (Array.isArray(p.edge)) {
          return p.edge.map(e => {
            const val = parseFloat(e.value);
            // Use backend side ("UP"/"DN") if available, otherwise fallback
            const dir = e.side || (val >= 0 ? 'UP' : 'DN');
            const color = val >= 0 ? 'green' : 'red';
            const absPct = Math.abs(val * 100).toFixed(1);
            // e.source is like "BINANCE", take first 3 chars
            const src = e.source ? e.source.substring(0, 3) : 'AVG';

            // Highlight AVG/CMB
            const isAvg = src === 'CMB';
            const labelStyle = isAvg ? 'color: #fff; font-weight: bold;' : 'font-size: 10px; width: 25px; display: inline-block;';

            return `<div class="pipe-row" style="margin-bottom: 2px;">
                          <span class="muted" style="${labelStyle}">${src}</span>
                          <span class="${color}">${dir} ${absPct}%</span>
                        </div>`;
          }).join('');
        }
        return `<div class="pipe-row"><span class="green">${p.edge}</span></div>`;
      })()
    },
    { title: '04 KELLY', content: `<div class="pipe-row"><span>${p.kelly}</span></div>` },
    { title: '05 EXEC', content: `<div class="pipe-row"><span class="green">${p.exec}</span></div>` }
  ];

  const html = steps.map(s => `
        <div class="pipe-step">
            <h5>${s.title}</h5>
            ${s.content}
        </div>
    `).join('');
  document.getElementById('pipelineContainer').innerHTML = html;
}

function renderPositions(list, activeContract) {
  const html = list.map(t => {
    let pnl = t.pnl || 0;
    let pnlClass = pnl >= 0 ? 'green' : 'red';
    let statusDisplay = t.status;

    // Live PnL Logic
    if (t.status === 'OPEN' && activeContract && t.slug === activeContract.slug) {
      // Attempt to get live price
      let prices = [];
      try {
        if (Array.isArray(activeContract.outcomePrices)) {
          prices = activeContract.outcomePrices.map(parseFloat);
        } else if (typeof activeContract.outcomePrices === 'string') {
          prices = JSON.parse(activeContract.outcomePrices).map(parseFloat);
        }
      } catch (e) { }

      if (prices.length >= 2) {
        const currentPrice = t.side === 'UP' ? prices[0] : prices[1];
        if (!isNaN(currentPrice) && t.entry_price) {
          // PnL per contract
          const diff = currentPrice - t.entry_price;
          // Start showing PnL based on 1000 contracts for visibility? 
          // or just the raw price diff? 
          // The backend PnL is "per unit" (max 1.0).
          // Let's show proper cents for unit PnL
          pnl = diff;
          pnlClass = pnl >= 0 ? 'green' : 'red';
          statusDisplay = `OPEN (${(currentPrice * 100).toFixed(1)}¢)`;
        }
      }
    }

    const cls = pnl >= 0 ? 'win' : 'loss'; // For border/bg logic if any
    const sideColor = t.side === 'UP' ? 'green' : 'red';
    const arrow = t.side === 'UP' ? '▲' : '▼';

    // Formatter for small PnL (cents)
    const fmtPnl = (val) => {
      if (Math.abs(val) < 10) return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(val);
      return fmtUsd(val);
    };

    return `
        <div class="pos-card ${cls}">
            <div class="pos-row">
                <span class="pos-label ${sideColor}">${arrow} ${t.side}</span>
                <span class="pos-amt ${pnlClass}">${fmtPnl(pnl)}</span>
            </div>
            <div class="pos-row">
                <span class="muted" style="font-size: 11px;">Ent: ${(t.entry_price * 100).toFixed(1)}¢</span>
                ${t.profit_target ? `<span class="muted" style="font-size: 11px;">Tgt: ${(t.profit_target * 100).toFixed(1)}¢</span>` : ''}
            </div>
            <div class="pos-row">
                <span class="pos-time">${t.entry_time.slice(11, 19)} · ${t.slug.slice(-4)}</span>
            </div>
            <div class="pos-row">
                <span class="pos-status muted">${statusDisplay}</span>
            </div>
        </div>
        `;
  }).join('');
  document.getElementById('positionsList').innerHTML = html;
}

// --- Charts ---

function initPnlChart() {
  const ctx = document.getElementById('pnlChart').getContext('2d');
  pnlChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        data: [],
        borderColor: '#ffffff',
        borderWidth: 1.5,
        tension: 0.1,
        pointRadius: 0,
        fill: {
          target: 'origin',
          above: 'rgba(255, 255, 255, 0.02)'
        }
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: {
          display: true,
          position: 'right',
          grid: { color: '#1a1a1a' },
          ticks: { color: '#555', font: { family: "'Roboto Mono', monospace", size: 9 } }
        }
      },
      animation: false
    }
  });
}

function updatePnlChart(labels, data) {
  if (!pnlChartInstance) return;
  pnlChartInstance.data.labels = labels;
  pnlChartInstance.data.datasets[0].data = data;
  pnlChartInstance.update();
}

// --- ApexCharts for BTC ---

function initBtcChart() {
  const options = {
    series: [{
      data: []
    }],
    chart: {
      type: 'candlestick',
      height: '100%',
      fontFamily: 'Roboto Mono, monospace',
      background: 'transparent',
      toolbar: { show: false },
      animations: { enabled: false }
    },
    theme: { mode: 'dark' },
    stroke: { width: 1 },
    xaxis: {
      type: 'datetime',
      axisBorder: { show: false },
      axisTicks: { show: false },
      labels: { style: { colors: '#555' } }
    },
    yaxis: {
      tooltip: { enabled: true },
      opposite: true,
      labels: { style: { colors: '#555' } }
    },
    grid: {
      borderColor: '#1a1a1a',
      strokeDashArray: 0,
    },
    plotOptions: {
      candlestick: {
        colors: {
          upward: '#00ff9d',
          downward: '#ff3333'
        },
        wick: { useFillColor: true }
      }
    }
  };

  btcChartInstance = new ApexCharts(document.querySelector("#btcChartContainer"), options);
  btcChartInstance.render();
}

function updateBtcChart(candles) {
  if (!btcChartInstance) return;

  // Convert API format to ApexCharts format
  // API: { timestamp: ms, open, high, low, close }
  // Apex: { x: timestamp, y: [O, H, L, C] }
  const data = candles.map(c => ({
    x: c.timestamp,
    y: [c.open, c.high, c.low, c.close]
  }));

  btcChartInstance.updateSeries([{
    data: data
  }]);

  if (candles.length > 0) {
    document.getElementById('btcPriceDisplay').innerText = fmtUsdCents(candles[candles.length - 1].close);
  }
}


// --- Main Loop ---

// --- Main Loop ---

let currentSource = "HYPERLIQUID";

const DUMMY_CONTRACT = {
  "id": "206937",
  "ticker": "btc-updown-5m-1771022100",
  "slug": "btc-updown-5m-1771022100",
  "title": "Bitcoin Up or Down - February 13, 5:35PM-5:40PM ET",
  "description": "This market will resolve to \"Up\" if the Bitcoin price at the end of the time range specified in the title is greater than or equal to the price at the beginning of that range. Otherwise, it will resolve to \"Down\".",
  "image": "https://polymarket-upload.s3.us-east-2.amazonaws.com/BTC+fullsize.png",
  "markets": [{
    "outcomes": "[\"Up\", \"Down\"]",
    "outcomePrices": "[\"0.505\", \"0.495\"]"
  }]
};

function renderContractInfo(c) {
  if (!c) return;

  // Parse prices/outcomes if they are strings (Polymarket API sometimes returns JSON strings)
  let prices = [];
  let outcomes = ["Up", "Down"]; // Default

  // Try to parse outcomePrices
  if (Array.isArray(c.outcomePrices)) {
    prices = c.outcomePrices;
  } else if (typeof c.outcomePrices === 'string') {
    try { prices = JSON.parse(c.outcomePrices); } catch (e) { }
  }

  // Try to parse outcomes
  if (Array.isArray(c.outcomes)) {
    outcomes = c.outcomes;
  } else if (typeof c.outcomes === 'string') {
    try { outcomes = JSON.parse(c.outcomes); } catch (e) { }
  }

  // Create prices array if missing or parse floats
  prices = prices.map(p => parseFloat(p));
  while (prices.length < outcomes.length) prices.push(0.5);

  const html = `
        <img src="${c.image || 'https://polymarket.com/images/fallback.png'}" class="contract-icon" alt="icon" onerror="this.style.display='none'">
        <div class="contract-details">
            <div class="contract-title" style="font-size: 11px;">${c.question || c.title}</div>
            <div class="contract-outcomes">
                <div class="outcome-badge outcome-up">
                    <span class="outcome-label">${outcomes[0] || 'UP'}</span>
                    <span class="outcome-price">${(prices[0] * 100).toFixed(1)}¢</span>
                </div>
                <div class="outcome-badge outcome-down">
                    <span class="outcome-label">${outcomes[1] || 'DOWN'}</span>
                    <span class="outcome-price">${(prices[1] * 100).toFixed(1)}¢</span>
                </div>
            </div>
        </div>
    `;
  document.getElementById('contractCard').innerHTML = html;
}



document.querySelectorAll('.tf-btn').forEach(btn => {
  btn.addEventListener('click', (e) => {
    document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
    e.target.classList.add('active');
    currentTimeframe = e.target.dataset.tf;
    refresh(); // Immediate refresh
  });
});

const sourceSelector = document.getElementById('chartSourceSelector');
if (sourceSelector) {
  sourceSelector.addEventListener('change', (e) => {
    currentSource = e.target.value;
    refresh();
  });
}

// --- Control Switches ---
function sendControlUpdate() {
  const binance = document.getElementById('toggleBinance').checked;
  const hyperliquid = document.getElementById('toggleHyperliquid').checked;
  const sim = document.getElementById('toggleSim').checked;

  console.log(`Updating Controls: Bin=${binance}, HL=${hyperliquid}, Sim=${sim}`);
  eel.update_controls({
    binance: binance,
    hyperliquid: hyperliquid,
    sim: sim
  });
}

['toggleBinance', 'toggleHyperliquid', 'toggleSim'].forEach(id => {
  const el = document.getElementById(id);
  if (el) {
    el.addEventListener('change', sendControlUpdate);
  }
});

initPnlChart();
initBtcChart();

// Render static contract info initially
renderContractInfo(DUMMY_CONTRACT);

async function refresh() {
  try {
    const data = await eel.get_dashboard_snapshot(currentTimeframe, currentSource)();

    if (!data) {
      console.warn("No data received from backend.");
      return;
    }

    try { renderHeader(data.header); } catch (e) { console.error("Error rendering Header:", e); }
    try { renderPnlSection(data.performance); } catch (e) { console.error("Error rendering PnL:", e); }
    try { renderPipeline(data.execution_pipeline); } catch (e) { console.error("Error rendering Pipeline:", e); }
    try { renderPositions(data.positions_log, data.active_contract); } catch (e) { console.error("Error rendering Positions:", e); }

    try {
      if (data.active_contract) {
        renderContractInfo(data.active_contract);
      }
    } catch (e) { console.error("Error rendering Contract:", e); }

    try {
      updatePnlChart(data.charts.timestamps, data.charts.equity);
    } catch (e) { console.error("Error updating PnL Chart:", e); }

    try {
      if (data.charts.candles) {
        updateBtcChart(data.charts.candles);
      }
    } catch (e) { console.error("Error updating BTC Chart:", e); }

  } catch (e) {
    console.error("Refresh loop failed:", e);
  }
}

refresh();
setInterval(refresh, 2000);
