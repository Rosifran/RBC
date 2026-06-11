#!/usr/bin/env python3
"""
patch_modo2_cockpit.py — Resultado do Modo 2 vira cockpit profissional.
Rodar de dentro de ~/RBC:  python3 patch_modo2_cockpit.py

Diagnóstico (2026-06-11):
- showModo2Result() (templates/index.html) é o único renderizador.
- Todas as variáveis (acaoAgora, status, gapHtml, strikesHtml, pmHtml,
  hardHtml, next_setup...) são calculadas ANTES do template final.
- Este patch substitui APENAS a montagem (const html = `...`) — entre os
  marcadores únicos `const html = \\`` e `const box = document.getElement...`.
  Nenhum cálculo, decisão, backend, rota ou JSON é alterado.

Nova hierarquia:
  1. HERO — Ação Agora (1º bloco; tag BLOCKED/WATCH/ALLOWED; score/risco discretos)
  2. Decision Summary — linha horizontal compacta (decisão·regime·SPY·VT·ZG·PW·Pivot)
  3. Alertas Prioritários — máx 3, consolidados (chase > evento > localização >
     vol premium > flow proxy); 1 borda vermelha só se houver bloqueio
  4. Próximo Setup + Plano de trade + Strikes (parte operacional, alta na tela)
  5. Accordion "Ver detalhes técnicos" (reusa modo5Toggle): Regime completo,
     Linha Operacional, Vol Premium, Flow Proxy, Localização, Âncoras,
     Intelligence Overlay, Timing/Gap, PM Note, Hard Rules completas.

Idempotente, com backup. Reverter: restaurar o backup gerado.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
INDEX = ROOT / 'templates' / 'index.html'
TS = datetime.now().strftime('%Y%m%d_%H%M%S')

START = "    const html = `"
END = "    const box = document.getElementById('modo2-result');"
MARKER = "Cockpit Modo 2"

NEW_ASSEMBLY = r'''    // ── Cockpit Modo 2 — alertas prioritários (máx 3, consolidados) ──
    const _alerts = [];
    if (d.chase_warning) _alerts.push({lv:'block', t:'CHASE — movimento já aconteceu. Não perseguir entrada.'});
    if (d.intelligence_block && d.intelligence_block.blocked) _alerts.push({lv:'block', t:'BLOQUEADO: ' + (((d.intelligence_block.primary_block||'').replace(/_/g,' ')) || 'camada de inteligência')});
    if (d.calendar_risk && ['HIGH','EXTREME'].indexOf(d.calendar_risk.risk_level) >= 0) _alerts.push({lv:'warn', t:'📅 ' + (d.calendar_risk.label || 'Evento econômico') + ' · risco ' + d.calendar_risk.risk_level});
    if (d.location && (d.location.location_zone === 'MIDDLE_OF_RANGE' || d.location.location_quality === 'DANGEROUS')) _alerts.push({lv:'warn', t:'Localização fraca: ' + (d.location.location_zone === 'MIDDLE_OF_RANGE' ? 'meio do range, sem edge estrutural' : (d.location.location_warning || 'posição perigosa'))});
    if (d.vol_premium && d.vol_premium.premium_state === 'EXPENSIVE') _alerts.push({lv:'warn', t:'Vol Premium CARO — prêmios inflados vs volatilidade realizada'});
    if (d.flow_proxy && ['FRAGILE_UP','SQUEEZE_RISK'].indexOf(d.flow_proxy.flow_state) >= 0) _alerts.push({lv:'warn', t:'Flow Proxy: ' + (d.flow_proxy.flow_state === 'FRAGILE_UP' ? 'alta frágil — VIX não confirma' : 'risco de squeeze')});
    const _top = _alerts.slice(0, 3);
    const _hasBlock = _top.some(a => a.lv === 'block');
    const alertsHtml = _top.length ? `
  <div style="background:#ffffff;border:0.5px solid #e2e8f0;border-left:4px solid ${_hasBlock ? '#dc2626' : '#fbbf24'};border-radius:12px;padding:8px 12px;">
    <div style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Alertas prioritários</div>
    ${_top.map(a => `<div style="font-size:12px;color:${a.lv==='block' ? '#dc2626' : '#92400e'};padding:2px 0;line-height:1.4;">${a.lv==='block' ? '⛔' : '⚠'} ${a.t}</div>`).join('')}
  </div>` : '';

    // ── hero: tag e cor ──
    const heroTag    = ((d.intelligence_block && d.intelligence_block.blocked) || d.chase_warning) ? 'BLOCKED' : (status === 'APROVO' ? 'ALLOWED' : 'WATCH');
    const heroBorder = heroTag === 'BLOCKED' ? '#dc2626' : heroTag === 'ALLOWED' ? '#16a34a' : '#fbbf24';
    const heroColor  = heroTag === 'BLOCKED' ? '#dc2626' : heroTag === 'ALLOWED' ? '#16a34a' : '#b45309';
    const _chip = (label, value, color) => value === null || value === undefined || value === '' ? '' :
      `<span style="font-size:11px;color:#94a3b8;white-space:nowrap;">${label} <b style="font-size:12px;color:${color || '#1e293b'};">${value}</b></span>`;

    const html = `
<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;display:grid;gap:8px;">

  <div style="background:#ffffff;border:0.5px solid #e2e8f0;border-top:4px solid ${heroBorder};border-radius:12px;padding:14px 16px;">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap;">
      <div style="min-width:0;">
        <div style="font-size:10px;color:#64748b;text-transform:uppercase;font-weight:700;letter-spacing:.06em;margin-bottom:4px;">Ação agora</div>
        <div style="font-size:20px;font-weight:600;color:${heroColor};line-height:1.2;">${acaoAgora}</div>
      </div>
      <span style="font-size:11px;background:${heroTag==='BLOCKED'?'#fef2f2':heroTag==='ALLOWED'?'#f0fdf4':'#fffbeb'};color:${heroColor};padding:4px 12px;border-radius:20px;font-weight:700;flex-shrink:0;">${heroTag}</span>
    </div>
    ${acaoDesc ? `<div style="font-size:12px;color:#475569;margin-top:6px;line-height:1.5;">${acaoDesc}</div>` : ''}
    <div style="font-size:11px;color:#94a3b8;margin-top:6px;">Score ${sc}/5 · Risco ${d.risk || '—'}</div>
  </div>

  <div style="background:#ffffff;border:0.5px solid #e2e8f0;border-radius:12px;padding:9px 14px;display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center;">
    ${_chip('Decisão', dec || 'NO TRADE', decColor)}
    ${_chip('Regime', regimeLabel, regimeColor)}
    ${_chip('SPY', sp ? sp.toFixed(2) : null)}
    ${_chip('VT', lv.vol_trigger ? parseFloat(lv.vol_trigger).toFixed(2) : null, '#d97706')}
    ${_chip('ZG', lv.zero_gamma ? parseFloat(lv.zero_gamma).toFixed(2) : null)}
    ${_chip('CW', lv.call_wall ? parseFloat(lv.call_wall).toFixed(2) : null, '#16a34a')}
    ${_chip('PW', lv.put_wall ? parseFloat(lv.put_wall).toFixed(2) : null, '#dc2626')}
    ${_chip('Pivot', (d.risk_pivot || d.risk_pivot === 0) ? parseFloat(d.risk_pivot).toFixed(2) : null, '#6366f1')}
  </div>

  ${alertsHtml}

${(() => {
    const ns = d.next_setup;
    if (!ns) return '';
    const rowNs = (color, label, text) => !text ? '' :
      `<div style="display:flex;align-items:baseline;border-left:3px solid ${color};margin-bottom:2px;">
        <span style="min-width:90px;padding:3px 8px;font-size:10px;font-weight:700;color:${color};text-transform:uppercase;flex-shrink:0;">${label}</span>
        <span style="padding:3px 8px;font-size:11px;color:#1e293b;line-height:1.5;flex:1;">${text}</span>
      </div>`;
    return `
  <div style="background:#fff;border:0.5px solid #e2e8f0;border-left:4px solid #6366f1;border-radius:12px;overflow:hidden;">
    <div style="padding:6px 12px;font-size:10px;font-weight:700;color:#6366f1;text-transform:uppercase;letter-spacing:.06em;border-bottom:0.5px solid #f1f5f9;background:#fafaff;">
      Próximo Setup a Monitorar
    </div>
    <div style="padding:6px 0 4px;">
      ${ns.context ? `<div style="padding:2px 12px 6px;font-size:11px;color:#64748b;font-style:italic;">${ns.context}</div>` : ''}
      ${rowNs('#16a34a', 'CALL',       ns.call_setup)}
      ${rowNs('#dc2626', 'PUT',        ns.put_setup)}
      ${rowNs('#64748b', 'NO TRADE',   ns.no_trade)}
      ${ns.key_level    ? rowNs('#6366f1', 'NÍVEL-CHAVE', ns.key_level)    : ''}
      ${ns.invalidation ? rowNs('#f97316', 'INVALIDAÇÃO', ns.invalidation) : ''}
    </div>
  </div>`;
  })()}

  ${!isNo && !(d.intelligence_block && d.intelligence_block.blocked) ? `
  <div style="background:#ffffff;border:0.5px solid #e2e8f0;border-radius:12px;overflow:hidden;">
    <div style="padding:8px 12px;font-size:10px;font-weight:500;color:#64748b;text-transform:uppercase;letter-spacing:.05em;border-bottom:0.5px solid #e2e8f0;">Plano de trade</div>
    ${d.entry ? `<div style="display:flex;gap:0;border-left:3px solid #bbf7d0;margin-bottom:1px;"><span style="min-width:72px;padding:5px 8px;font-size:10px;font-weight:500;color:#16a34a;text-transform:uppercase;flex-shrink:0;">Entrada</span><span style="padding:5px 8px;font-size:12px;color:#1e293b;line-height:1.4;flex:1;">${d.entry}</span></div>` : ''}
    ${d.stop  ? `<div style="display:flex;gap:0;border-left:3px solid #fecaca;margin-bottom:1px;"><span style="min-width:72px;padding:5px 8px;font-size:10px;font-weight:500;color:#dc2626;text-transform:uppercase;flex-shrink:0;">Stop</span><span style="padding:5px 8px;font-size:12px;color:#1e293b;line-height:1.4;flex:1;">${d.stop}</span></div>` : ''}
    ${d.target_1 ? `<div style="display:flex;gap:0;border-left:3px solid #bfdbfe;margin-bottom:1px;"><span style="min-width:72px;padding:5px 8px;font-size:10px;font-weight:500;color:#2563eb;text-transform:uppercase;flex-shrink:0;">Alvo 1</span><span style="padding:5px 8px;font-size:12px;color:#1e293b;line-height:1.4;flex:1;">${d.target_1}</span></div>` : ''}
    ${d.target_2 ? `<div style="display:flex;gap:0;border-left:3px solid #8b5cf6;"><span style="min-width:72px;padding:5px 8px;font-size:10px;font-weight:500;color:#8b5cf6;text-transform:uppercase;flex-shrink:0;">Alvo 2</span><span style="padding:5px 8px;font-size:12px;color:#1e293b;line-height:1.4;flex:1;">${d.target_2}</span></div>` : ''}
  </div>` : `
  <div style="background:#f8fafc;border-radius:12px;padding:10px 14px;">
    <div style="font-size:12px;color:#64748b;line-height:1.6;">${(d.location && d.location.location_report) ? d.location.location_report : (d.reason || 'SPY no meio da faixa, sem edge estrutural.')}</div>
    ${d.location && d.location.nearest_resistance && d.location.nearest_support ? `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px;">
      <div style="background:#ffffff;border:0.5px solid #e2e8f0;border-radius:8px;padding:8px 10px;">
        <div style="font-size:10px;color:#64748b;">Resistência mais próxima</div>
        <div style="font-size:14px;font-weight:500;color:#16a34a;">${d.location.nearest_resistance}</div>
        <div style="font-size:10px;color:#94a3b8;">${d.location.nearest_resistance_type || ''}</div>
      </div>
      <div style="background:#ffffff;border:0.5px solid #e2e8f0;border-radius:8px;padding:8px 10px;">
        <div style="font-size:10px;color:#64748b;">Suporte mais próximo</div>
        <div style="font-size:14px;font-weight:500;color:#dc2626;">${d.location.nearest_support}</div>
        <div style="font-size:10px;color:#94a3b8;">${d.location.nearest_support_type || ''}</div>
      </div>
    </div>` : ''}
  </div>`}

  ${strikesHtml}

  <div style="background:#ffffff;border:0.5px solid #e2e8f0;border-radius:12px;overflow:hidden;">
    <div onclick="modo5Toggle('m2-tech')" style="padding:10px 14px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;">
      <span style="font-size:11px;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.05em;">Ver detalhes técnicos</span>
      <span id="m2-tech-ch" style="font-size:11px;color:#94a3b8;">▸</span>
    </div>
    <div id="m2-tech" style="display:none;">
      <div style="display:grid;gap:8px;padding:0 12px 12px;">

  <div style="background:#fafafa;border:0.5px solid #e2e8f0;border-radius:12px;padding:10px 14px;">
    <div style="font-size:11px;font-weight:500;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">Regime</div>
    <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-bottom:8px;">
      <div style="background:#f8fafc;border-radius:8px;padding:8px 10px;">
        <div style="font-size:10px;color:#64748b;">SPY</div>
        <div style="font-size:16px;font-weight:500;color:#1e293b;">${sp ? sp.toFixed(2) : '—'}</div>
      </div>
      <div style="background:#f8fafc;border-radius:8px;padding:8px 10px;">
        <div style="font-size:10px;color:#64748b;">Regime</div>
        <div style="font-size:13px;font-weight:500;color:${regimeColor};">${regimeLabel}</div>
      </div>
      ${lv.vol_trigger ? `<div style="background:#f8fafc;border-radius:8px;padding:8px 10px;">
        <div style="font-size:10px;color:#64748b;">Vol Trigger</div>
        <div style="font-size:16px;font-weight:500;color:#d97706;">${parseFloat(lv.vol_trigger).toFixed(2)}</div>
      </div>` : ''}
      ${lv.zero_gamma ? `<div style="background:#f8fafc;border-radius:8px;padding:8px 10px;">
        <div style="font-size:10px;color:#64748b;">Zero Gamma</div>
        <div style="font-size:16px;font-weight:500;color:#1e293b;">${parseFloat(lv.zero_gamma).toFixed(2)}</div>
      </div>` : ''}
      ${lv.call_wall ? `<div style="background:#f8fafc;border-radius:8px;padding:8px 10px;">
        <div style="font-size:10px;color:#64748b;">Call Wall</div>
        <div style="font-size:16px;font-weight:500;color:#16a34a;">${parseFloat(lv.call_wall).toFixed(2)}</div>
      </div>` : ''}
      ${lv.put_wall ? `<div style="background:#f8fafc;border-radius:8px;padding:8px 10px;">
        <div style="font-size:10px;color:#64748b;">Put Wall</div>
        <div style="font-size:16px;font-weight:500;color:#dc2626;">${parseFloat(lv.put_wall).toFixed(2)}</div>
      </div>` : ''}
    </div>
    ${d.operational_regime_line ? `
    <div style="padding:8px 10px;background:#fafaff;border:0.5px solid #e0e7ff;border-radius:8px;">
      <div style="font-size:10px;color:#6366f1;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px;">Linha Operacional</div>
      <div style="font-size:12px;color:#1e293b;line-height:1.5;">${d.operational_regime_source === 'RISK_PIVOT' ? 'Risk Pivot' : 'Vol Trigger'} <b>${parseFloat(d.operational_regime_line).toFixed(2)}</b>${(d.distance_to_operational_pct || d.distance_to_operational_pct === 0) ? ` · SPY ${d.distance_to_operational_pct > 0 ? '+' : ''}${d.distance_to_operational_pct.toFixed(2)}% ${d.distance_to_operational_pct >= 0 ? 'acima' : 'abaixo'}` : ''}${d.regime_strength === 'extended' ? ` <span style="color:#dc2626;font-weight:600;">· ESTICADO — chase risk</span>` : d.regime_strength === 'transition' ? ` <span style="color:#d97706;font-weight:600;">· zona de TRANSICAO — toque nao e aceitacao</span>` : d.regime_strength === 'clear' ? ` <span style="color:#16a34a;">· regime claro</span>` : d.regime_strength === 'moderate' ? ` <span style="color:#64748b;">· regime moderado</span>` : ''}</div>
      ${d.operational_note ? `<div style="font-size:11px;color:#92400e;margin-top:4px;">⚠ ${d.operational_note}</div>` : ''}
      ${d.vol_premium ? `<div style="font-size:11px;color:#475569;margin-top:4px;padding-top:4px;border-top:0.5px solid #e0e7ff;">Vol Premium: VIX <b>${d.vol_premium.vix}</b> → RV esperada ~${d.vol_premium.implied_rv}% · RV1M ${d.vol_premium.rv_1m}% <span style="font-weight:600;color:${d.vol_premium.premium_state === 'EXPENSIVE' ? '#dc2626' : d.vol_premium.premium_state === 'CHEAP' ? '#16a34a' : '#64748b'};">${d.vol_premium.premium_state === 'EXPENSIVE' ? 'CARO' : d.vol_premium.premium_state === 'CHEAP' ? 'BARATO' : 'JUSTO'}</span>${(d.vol_premium.rv_5d !== null && d.vol_premium.rv_5d !== undefined) ? ` · RV5D ${d.vol_premium.rv_5d}%${d.vol_premium.rv_trend === 'ACCELERATING' ? ` <span style="color:#d97706;font-weight:600;">acelerando</span>` : d.vol_premium.rv_trend === 'COOLING' ? ' esfriando' : ' estável'}` : ''}</div>` : ''}
      ${d.flow_proxy ? `<div style="font-size:11px;color:#475569;margin-top:4px;padding-top:4px;border-top:0.5px solid #e0e7ff;">Flow Proxy ${d.flow_proxy.window_min}min: SPY ${d.flow_proxy.spy_chg_pct > 0 ? '+' : ''}${d.flow_proxy.spy_chg_pct}% · VIX ${d.flow_proxy.vix_chg_pct > 0 ? '+' : ''}${d.flow_proxy.vix_chg_pct}% → <span style="font-weight:600;color:${d.flow_proxy.flow_state === 'CONFIRMING_UP' ? '#16a34a' : d.flow_proxy.flow_state === 'CONFIRMING_DOWN' ? '#dc2626' : d.flow_proxy.flow_state === 'FRAGILE_UP' ? '#d97706' : d.flow_proxy.flow_state === 'SQUEEZE_RISK' ? '#7c3aed' : '#64748b'};">${d.flow_proxy.flow_state === 'CONFIRMING_UP' ? 'CONFIRMANDO ALTA' : d.flow_proxy.flow_state === 'CONFIRMING_DOWN' ? 'CONFIRMANDO QUEDA' : d.flow_proxy.flow_state === 'FRAGILE_UP' ? 'ALTA FRÁGIL' : d.flow_proxy.flow_state === 'SQUEEZE_RISK' ? 'RISCO DE SQUEEZE' : 'NEUTRO'}</span></div>` : ''}
    </div>` : ''}
    ${d.location && d.location.range_position !== null && d.location.range_position !== undefined ? `
    <div style="margin-top:6px;padding:8px 10px;background:#fafafa;border:0.5px solid #e2e8f0;border-radius:8px;">
      <div style="font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px;">Localização ${d.location.location_quality ? `<span style="float:right;color:${d.location.location_quality === 'DANGEROUS' ? '#dc2626' : d.location.location_quality === 'STRONG' ? '#16a34a' : d.location.location_quality === 'MEDIUM' ? '#d97706' : '#64748b'};">${d.location.location_quality}</span>` : ''}</div>
      <div style="font-size:12px;color:#1e293b;line-height:1.5;">Suporte <b>${d.location.nearest_support}</b> <span style="color:#94a3b8;font-size:10px;">${d.location.nearest_support_type || ''}</span> · posição <b>${d.location.range_position}</b>${d.location.location_zone === 'MIDDLE_OF_RANGE' ? ` <span style="color:#dc2626;font-weight:600;">· MEIO DO RANGE</span>` : d.location.location_zone === 'NEAR_RESISTANCE' ? ` <span style="color:#d97706;font-weight:600;">· colado na resistência</span>` : d.location.location_zone === 'NEAR_SUPPORT' ? ` <span style="color:#d97706;font-weight:600;">· colado no suporte</span>` : d.location.location_zone === 'UPPER_RANGE' ? ` · parte alta` : ` · parte baixa`} · Resistência <b>${d.location.nearest_resistance}</b> <span style="color:#94a3b8;font-size:10px;">${d.location.nearest_resistance_type || ''}</span></div>
      ${d.location.location_warning ? `<div style="font-size:11px;color:#92400e;margin-top:4px;">⚠ ${d.location.location_warning}</div>` : ''}
    </div>` : ''}
    ${d.anchors ? `
    <div style="margin-top:6px;padding:8px 10px;background:#fafafa;border:0.5px solid #e2e8f0;border-radius:8px;">
      <div style="font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px;">Âncoras</div>
      <div style="font-size:12px;color:#1e293b;line-height:1.7;">↑ CALL: ${d.anchors.upside.quality === 'NONE' ? `<span style="color:#dc2626;font-weight:600;">sem âncora — sem destino estrutural</span>` : `<b>${d.anchors.upside.price}</b> <span style="color:#94a3b8;font-size:10px;">${d.anchors.upside.type}</span> · ${d.anchors.upside.distance_pts} pts <span style="color:${d.anchors.upside.quality === 'HIGH' ? '#16a34a' : d.anchors.upside.quality === 'MEDIUM' ? '#d97706' : '#64748b'};font-weight:600;">${d.anchors.upside.quality}</span>${d.anchors.upside.reached ? ` <span style="color:#dc2626;font-weight:600;">· JÁ ALCANÇADA</span>` : ''}`}<br>↓ PUT: ${d.anchors.downside.quality === 'NONE' ? `<span style="color:#dc2626;font-weight:600;">sem âncora — sem destino estrutural</span>` : `<b>${d.anchors.downside.price}</b> <span style="color:#94a3b8;font-size:10px;">${d.anchors.downside.type}</span> · ${d.anchors.downside.distance_pts} pts <span style="color:${d.anchors.downside.quality === 'HIGH' ? '#16a34a' : d.anchors.downside.quality === 'MEDIUM' ? '#d97706' : '#64748b'};font-weight:600;">${d.anchors.downside.quality}</span>${d.anchors.downside.reached ? ` <span style="color:#dc2626;font-weight:600;">· JÁ ALCANÇADA</span>` : ''}`}</div>
      ${d.anchors.anchor_note ? `<div style="font-size:11px;color:#92400e;margin-top:4px;">⚠ ${d.anchors.anchor_note}</div>` : ''}
    </div>` : ''}
  </div>

  ${d.intelligence_block ? (() => {
    const ib = d.intelligence_block;
    const q  = ib.entry_quality;
    const qColor = q === 'GOOD' ? '#16a34a' : q === 'CAUTION' ? '#d97706' : q === 'POOR' ? '#ea580c' : '#dc2626';
    const qBg    = q === 'GOOD' ? '#f0fdf4' : q === 'CAUTION' ? '#fffbeb' : q === 'POOR' ? '#fff7ed' : '#fef2f2';
    return `
  <div style="background:${qBg};border:0.5px solid #e2e8f0;border-left:4px solid ${qColor};border-radius:12px;padding:10px 14px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
      <span style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.05em;">Intelligence Overlay</span>
      <span style="font-size:11px;font-weight:700;color:${qColor};">${q}${ib.suggested_action ? ' · ' + ib.suggested_action.replace(/_/g, ' ') : ''}</span>
    </div>
    ${ib.blocked ? `<div style="font-size:12px;font-weight:700;color:#dc2626;margin-bottom:3px;">🚫 TRADE BLOQUEADO PELA CAMADA DE INTELIGENCIA</div>` : ''}
    ${ib.primary_block ? `<div style="font-size:11px;font-weight:600;color:${qColor};margin-bottom:3px;">${ib.primary_block.replace(/_/g, ' ')}</div>` : ''}
    ${ib.report ? `<div style="font-size:12px;color:#1e293b;line-height:1.5;">${ib.report}</div>` : ''}
    ${ib.alternative ? `<div style="font-size:11px;color:#64748b;margin-top:4px;"><b>Alternativa:</b> ${ib.alternative}</div>` : ''}
    ${(d.calendar_risk && d.calendar_risk.note && ['HIGH','EXTREME'].indexOf(d.calendar_risk.risk_level) >= 0) ? `<div style="font-size:11px;color:#7c2d12;margin-top:6px;padding-top:6px;border-top:0.5px solid rgba(0,0,0,0.08);">📅 ${d.calendar_risk.note}</div>` : ''}
  </div>`;
  })() : ''}

  ${gapHtml}

  ${pmHtml}

  ${hardHtml ? `
  <div style="background:#fafafa;border:0.5px solid #e2e8f0;border-radius:12px;padding:8px 12px;">
    <div style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px;">Hard Rules</div>
    ${hardHtml}
  </div>` : ''}

      </div>
    </div>
  </div>

</div>`;

'''


def main():
    print("patch_modo2_cockpit.py — Resultado Modo 2 em formato cockpit\n")
    if not INDEX.exists():
        print("ERRO: templates/index.html nao encontrado. Rode de dentro de ~/RBC.")
        sys.exit(1)
    text = INDEX.read_text(encoding='utf-8')
    if MARKER in text:
        print("  ja aplicado — nada a fazer.")
        return
    if text.count(START) != 1 or text.count(END) != 1:
        print(f"  marcadores: START={text.count(START)}x END={text.count(END)}x (esperado 1/1) — abortado.")
        sys.exit(1)
    i, j = text.index(START), text.index(END)
    if not (0 < i < j):
        print("  ordem dos marcadores invalida — abortado.")
        sys.exit(1)

    dst = INDEX.with_name(f"index_backup_{TS}.html")
    shutil.copy2(INDEX, dst)
    print(f"  backup: templates/{dst.name}")

    INDEX.write_text(text[:i] + NEW_ASSEMBLY + text[j:], encoding='utf-8')
    print("  showModo2Result: montagem substituida (hero > summary > alertas > plano > accordion)")
    print("""
Proximos passos:
  git add templates/index.html patch_modo2_cockpit.py
  git commit -m "UI Modo 2: cockpit profissional (hero Acao Agora, alertas consolidados, detalhes em accordion)"
  git push
Apos o deploy: Cmd+Shift+R no Modo 2 e rodar uma analise.
""")


if __name__ == '__main__':
    main()
