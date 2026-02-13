const fmtUsd = (n) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(n || 0);
let pnlChart, priceChart, equityChart;

function colorPnL(v){ return (v||0) >= 0 ? 'green' : 'red'; }

function renderTopbar(h){
  const items = [
    ['Asset', `${h.asset} ${fmtUsd(h.price)}`],
    ['Total PNL', fmtUsd(h.total_pnl), colorPnL(h.total_pnl)],
    ['Daily PNL', fmtUsd(h.daily_pnl), colorPnL(h.daily_pnl)],
    ['Win Rate', `${h.win_rate}%`],
    ['Total Trades', h.total_trades],
    ['Open Exposure', fmtUsd(h.open_exposure), 'yellow'],
    ['Next Window', `${h.next_window_seconds}s`],
    ['Market Session', h.market_session],
  ];
  topbar.innerHTML = items.map(([k,v,c]) => `<div class="stat"><div class="label">${k}</div><div class="value ${c||''}">${v}</div></div>`).join('');
}

function metricCard(label, value, cls=''){ return `<div class="metric"><div class="label">${label}</div><div class="value ${cls}">${value}</div></div>` }

function renderMetrics(p){
  perfMetrics.innerHTML = [
    metricCard('AVG / TRADE', fmtUsd(p.avg_trade), 'green'),
    metricCard('MAX DD', fmtUsd(p.max_dd), 'red'),
    metricCard('KELLY F*', `${p.kelly_f}%`),
    metricCard('SHARPE', p.sharpe),
    metricCard('OPEN POS', fmtUsd(p.total), 'yellow'),
    metricCard('DD LIMIT', `${p.dd_limit}%`, 'red'),
  ].join('');
}

function drawOrUpdateChart(ctxId, chartObj, labels, values, color, fill=false){
  const ctx = document.getElementById(ctxId);
  if(!ctx) return chartObj;
  if(chartObj){ chartObj.data.labels=labels; chartObj.data.datasets[0].data=values; chartObj.update('none'); return chartObj; }
  return new Chart(ctx, {type:'line', data:{labels, datasets:[{data:values,borderColor:color,backgroundColor:fill?`${color}33`:'transparent',fill,tension:.2,pointRadius:0}]}, options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{display:false},y:{ticks:{color:'#95a3bf'}}}}});
}

function renderOrderFeed(feed){
  orderFeed.innerHTML = feed.map(o => `<div class='feed-item'><span>${o.time} | ${o.window}</span><span class='${o.side==='UP'?'green':'red'}'>${o.side}</span><span>${o.entry}¢</span><span>${fmtUsd(o.size)}</span></div>`).join('');
}

function renderSignalFlow(rows){
  signalFlow.innerHTML = rows.map(r => `<div class='sig'><b>${r.exchange}</b><div class='${r.signal>=0?'green':'red'}'>Signal ${r.signal}</div><div>Latency ${r.latency}ms</div></div>`).join('');
}

function renderPipeline(p){
  const map = [['CEX FEEDS',p.cex_feeds],['PM ODDS',p.pm_odds],['EDGE',p.edge],['KELLY',p.kelly],['EXEC',p.exec]];
  pipeline.innerHTML = map.map(s => `<div class='step'><div class='label'>${s[0]}</div><div>${s[1]}</div></div>`).join('');
}

function renderPositions(items){
  positionsLog.innerHTML = items.map(t => {
    const pnl = t.pnl ?? 0;
    const status = t.status === 'CLOSED' ? (pnl > 0 ? 'resolved ✓' : 'stopped ✕') : 'open';
    return `<div class='pos-item'><span>${t.side}</span><span>${status}</span><span class='${pnl>=0?'green':'red'}'>${fmtUsd(pnl)}</span></div>`;
  }).join('');
}

async function refresh(){
  try {
    const data = await eel.get_dashboard_snapshot()();
    renderTopbar(data.header);
    renderMetrics(data.performance);
    renderOrderFeed(data.order_feed);
    renderSignalFlow(data.signal_flow);
    renderPipeline(data.execution_pipeline);
    renderPositions(data.positions_log);

    pnlChart = drawOrUpdateChart('pnlChart', pnlChart, data.charts.timestamps, data.charts.equity, '#22c55e', true);
    priceChart = drawOrUpdateChart('priceChart', priceChart, data.charts.timestamps, data.charts.prices, '#60a5fa');
    equityChart = drawOrUpdateChart('equityChart', equityChart, data.charts.timestamps, data.charts.volumes, '#f59e0b');
  } catch (e) {
    console.error('dashboard refresh failed', e);
  }
}

refresh();
setInterval(refresh, 2000);
