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
  const steps = [
    { title: '01 CEX FEEDS', content: `<div class="pipe-row"><span>Sources</span> <span>${p.cex_feeds.split(',')[0]}...</span></div>` },
    { title: '02 PM ODDS', content: `<div class="pipe-row"><span>${p.pm_odds}</span></div>` },
    { title: '03 EDGE', content: `<div class="pipe-row"><span class="green">${p.edge}</span></div>` },
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

function renderPositions(list) {
  const html = list.map(t => {
    const pnl = t.pnl || 0;
    const cls = pnl >= 0 ? 'win' : 'loss';
    const sideColor = t.side === 'UP' ? 'green' : 'red';
    const pnlColor = pnl >= 0 ? 'green' : 'red';
    const arrow = t.side === 'UP' ? '▲' : '▼';

    return `
        <div class="pos-card ${cls}">
            <div class="pos-row">
                <span class="pos-label ${sideColor}">${arrow} ${t.side}</span>
                <span class="pos-amt ${pnlColor}">${fmtUsd(pnl)}</span>
            </div>
            <div class="pos-row">
                <span class="pos-time">${t.entry_time.slice(11, 19)} · ${t.slug}</span>
            </div>
            <div class="pos-row">
                <span class="pos-status muted">${t.status}</span>
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
  // Parse prices if they are strings
  let prices = c.markets[0].outcomePrices;
  if (typeof prices === 'string') prices = JSON.parse(prices);

  const html = `
        <img src="${c.image}" class="contract-icon" alt="icon">
        <div class="contract-details">
            <div class="contract-title">${c.title}</div>
            <div class="contract-outcomes">
                <div class="outcome-badge outcome-up">
                    <span class="outcome-label">UP</span>
                    <span class="outcome-price">${(parseFloat(prices[0]) * 100).toFixed(1)}¢</span>
                </div>
                <div class="outcome-badge outcome-down">
                    <span class="outcome-label">DOWN</span>
                    <span class="outcome-price">${(parseFloat(prices[1]) * 100).toFixed(1)}¢</span>
                </div>
            </div>
        </div>
    `;
  document.getElementById('contractCard').innerHTML = html;
}

async function refresh() {
  try {
    const data = await eel.get_dashboard_snapshot(currentTimeframe)();

    renderHeader(data.header);
    renderPnlSection(data.performance);
    // renderOrderFeed(data.order_feed); // REMOVED
    renderPipeline(data.execution_pipeline);
    renderPositions(data.positions_log);

    updatePnlChart(data.charts.timestamps, data.charts.equity);

    if (data.charts.candles) {
      updateBtcChart(data.charts.candles);
    }

  } catch (e) {
    console.error("Refresh failed:", e);
  }
}

// --- Init ---

document.querySelectorAll('.tf-btn').forEach(btn => {
  btn.addEventListener('click', (e) => {
    document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
    e.target.classList.add('active');
    currentTimeframe = e.target.dataset.tf;
    refresh(); // Immediate refresh
  });
});

initPnlChart();
initBtcChart();

// Render static contract info
renderContractInfo(DUMMY_CONTRACT);

refresh();
setInterval(refresh, 2000);
