'use strict';
const $=id=>document.getElementById(id), names={deepseek:'DeepSeek',kimi:'Kimi',openai:'OpenAI / Codex API'}, colors={deepseek:'#4978f5',kimi:'#a18ae9',openai:'#3cb697'};
const esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const compact=x=>new Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:2}).format(x);
const integer=x=>x===null||x===undefined?'未知':Number(x).toLocaleString('en-US');
const money=x=>new Intl.NumberFormat('zh-CN',{style:'currency',currency:'CNY'}).format(x);
let data=null,page=0,currentView='overview',ticket=0;
const day=d=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);
$('end').value=day(new Date()); $('start').value=day(new Date(Date.now()-29*86400000));
function toast(msg){$('toast').textContent=msg;$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,4500);}
async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const j=await r.json();if(!r.ok)throw Error(j.error||'请求失败');return j;}
function params(){return new URLSearchParams({mode:$('live').checked?'live':'demo',source:$('source').value,provider:$('provider').value,model:$('model').value,project:$('project').value,start:$('start').value,end:$('end').value});}
function selectOptions(id,values){const old=$(id).value;$(id).innerHTML=`<option value="all">全部${id==='model'?'模型':'项目'}</option>`+values.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');if(values.includes(old))$(id).value=old;}
async function load(){const seq=++ticket;$('error').hidden=true;try{const d=await api('/api/dashboard?'+params());if(seq!==ticket)return;data=d;page=0;render();}catch(e){if(seq===ticket){$('error').textContent=e.message;$('error').hidden=false;}}}
function total(rows,k){return rows.reduce((a,r)=>a+(r[k]??0),0);}
function cny(r){if(r.cost===null||r.cost===undefined)return null; if(r.currency==='CNY')return Number(r.cost);if(r.currency==='USD')return Number(r.cost)*Number(data.usd_to_cny);return null;}
function render(){
 const rows=data.events, known=rows.filter(r=>cny(r)!==null), cost=known.reduce((a,r)=>a+cny(r),0), inp=total(rows,'input_tokens'),out=total(rows,'output_tokens');
 selectOptions('model',data.options.model);selectOptions('project',data.options.project);
 const live=data.mode==='live';$('mode-banner').classList.toggle('live',live);
 $('mode-banner').querySelector('strong').textContent=live?'真实数据模式 · 只展示已采集的数据':'正在浏览演示数据';
 $('mode-banner').querySelector('p').textContent=live?'余额、官方用量与本地调用记录独立展示。尚未采集的历史用量不可自动补全。':'用于预览界面，所有数值均为模拟。切换真实数据后可查看你的账户。';
 $('sync').disabled=!live;$('import-file').disabled=!live;
 $('cost').textContent=known.length?money(cost):'—';
 $('cost-note').textContent=rows.length?`${known.length} / ${rows.length} 条记录已计价 · 参考折算`:'当前范围暂无数据';
 const incomplete=rows.some(r=>r.input_tokens===null||r.output_tokens===null);
 $('tokens').textContent=rows.length?compact(inp+out)+(incomplete?' + ?':''):'—';
 $('token-note').textContent=incomplete?'仅汇总已知 Token，部分字段缺失':'输入 '+compact(inp)+' / 输出 '+compact(out);
 $('requests').textContent=rows.length?integer(total(rows,'requests')):'—';
 $('request-note').textContent=data.source==='official'?'OpenAI 官方日聚合请求数':'已采集的 API 调用次数';
 const cacheRows=rows.filter(r=>r.cached_tokens!==null&&r.input_tokens!==null),cacheInput=total(cacheRows,'input_tokens');
 $('cache').textContent=cacheInput?(total(cacheRows,'cached_tokens')/cacheInput*100).toFixed(1)+'%':'—';
 $('updated').textContent='页面更新 '+new Date(data.generated_at).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
 $('config-path').textContent=data.config_path;
 $('budget-input').value=data.budget;
 $('fx-note').textContent=`USD → CNY：${data.usd_to_cny}。${data.exchange_rate_note}。预算按当前选择的日期、来源和过滤条件比较。`;
 chart(rows);distribution(rows);ranking(rows);budget(cost,known.length,rows.length);accounts();table();billing();
}
function chart(rows){
 if(!rows.length){$('chart').innerHTML='<div class="empty">暂无用量记录 · 接入采集或切换演示模式</div>';return;}
 const buckets={};for(let t=new Date(data.start+'T00:00:00Z');dayUTC(t)<=data.end;t=new Date(t.getTime()+86400000))buckets[dayUTC(t)]={input:0,output:0};
 rows.forEach(r=>{const d=r.time.slice(0,10);if(buckets[d]){buckets[d].input+=r.input_tokens??0;buckets[d].output+=r.output_tokens??0;}});
 const days=Object.keys(buckets),max=Math.max(1,...Object.values(buckets).map(x=>x.input+x.output)),W=700,H=215,left=48,bottom=185,top=15,step=(W-left-10)/days.length,bw=Math.min(16,step*.58);
 let svg='';for(let i=0;i<=4;i++){const y=bottom-(bottom-top)*i/4;svg+=`<line x1="${left}" y1="${y}" x2="${W}" y2="${y}" stroke="#edf1f6" stroke-dasharray="3 5"/><text x="${left-9}" y="${y+3}" text-anchor="end" fill="#a2aec0" font-size="9">${compact(max*i/4)}</text>`;}
 days.forEach((d,i)=>{const x=left+step*(i+.5),b=buckets[d],hi=b.input/max*(bottom-top),ho=b.output/max*(bottom-top);svg+=`<g><title>${esc(d)} 输入 ${integer(b.input)} / 输出 ${integer(b.output)}</title><rect x="${x-bw/2}" y="${bottom-hi}" width="${bw}" height="${hi}" rx="2" fill="#547ff4"/><rect x="${x-bw/2}" y="${bottom-hi-ho}" width="${bw}" height="${ho}" rx="2" fill="#bccdfc"/></g>`;if(i%Math.max(1,Math.ceil(days.length/7))===0||i===days.length-1)svg+=`<text x="${x}" y="207" text-anchor="middle" fill="#9ca9bc" font-size="9">${d.slice(5).replace('-','/')}</text>`;});
 $('chart').innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">${svg}</svg>`;
}
function dayUTC(d){return d.toISOString().slice(0,10);}
function distribution(rows){const vals=Object.keys(names).map(p=>({p,v:total(rows.filter(r=>r.provider===p),'input_tokens')+total(rows.filter(r=>r.provider===p),'output_tokens')})),sum=vals.reduce((a,r)=>a+r.v,0);let end=0;const gradients=vals.map(({p,v})=>{const start=end;end+=sum?v/sum*100:0;return `${colors[p]} ${start}% ${end}%`;});$('donut').style.background=sum?`conic-gradient(${gradients.join(',')})`:'#edf1f6';$('donut-total').textContent=sum?compact(sum):'—';$('distribution').innerHTML=vals.map(({p,v})=>`<div class="dist-row"><span class="dot" style="background:${colors[p]}"></span>${esc(names[p])}<b>${sum?(v/sum*100).toFixed(1)+'%':'—'}</b></div>`).join('');}
function ranking(rows){const groups={};rows.forEach(r=>{const key=r.provider+'/'+r.model;groups[key]=(groups[key]||0)+(r.input_tokens??0)+(r.output_tokens??0);});const ranked=Object.entries(groups).sort((a,b)=>b[1]-a[1]).slice(0,5),max=Math.max(1,...ranked.map(x=>x[1]));$('ranking').innerHTML=ranked.length?ranked.map(([k,v],i)=>`<div class="rank-row"><span class="rank-num">${String(i+1).padStart(2,'0')}</span><span class="rank-model" title="${esc(k)}">${esc(k.split('/').slice(1).join('/'))}</span><div class="bar"><span style="width:${v/max*100}%"></span></div><b>${compact(v)}</b></div>`).join(''):'<div class="empty">暂无模型记录</div>';}
function budget(cost,known,count){const amount=Number(data.budget),pct=cost/amount*100,color=pct>=100?'#dc6565':pct>=80?'#e9ad4b':'#4978f5';const text=!known?'暂无可计价记录':pct>=100?'已达到预算，请检查消耗':pct>=80?'已使用 80% 以上预算':pct>=50?'已使用 50% 以上预算':'预算范围内';const html=`<div class="budget-value">${known?money(cost):'—'} <small>/ ${money(amount)}</small></div><div class="budget-track"><span style="width:${Math.min(100,pct)}%;background:${color}"></span></div><div class="budget-line"><span>${esc(text)}</span><strong>${known?pct.toFixed(1)+'%':'—'}</strong></div><p class="muted">${known} / ${count} 条记录已计价${data.mode==='demo'?' · 演示费用':''}</p>`;$('budget-overview').innerHTML=html;$('budget-detail').innerHTML=html;}
function accounts(){
 $('account-cards').innerHTML=Object.entries(data.accounts).map(([p,a])=>`<article class="account"><div class="account-head"><span class="provider-logo ${p}">${p==='deepseek'?'D':p==='kimi'?'K':'◎'}</span>${esc(names[p])}<span class="tag">${a.status==='ok'?'已同步':a.status==='demo'?'演示':a.status==='error'?'同步异常':'待配置'}</span></div><strong>${a.balances?.length?a.balances.map(b=>esc(b.currency)+' '+esc(b.amount)).join(' / '):'—'}</strong><p>${esc(a.message)}</p><p>${a.synced_at?'最近成功同步 '+esc(new Date(a.synced_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})):'暂无官方同步时间'}</p></article>`).join('');
 const fields={deepseek:'deepseek_api_key',kimi:'kimi_api_key',openai:'openai_admin_key'};
 $('connections').innerHTML=Object.entries(data.accounts).map(([p,a])=>`<div class="connection"><h4>${esc(names[p])} <span class="tag">${data.mode==='demo'?'演示模式':a.configured?'密钥已配置':'密钥未配置'}</span></h4><p>配置字段：<code>${fields[p]}</code></p><p>${esc(a.message)}</p><p>${p==='openai'?'需要 OpenAI 组织 Admin Key；支持官方 completions 用量与组织费用，不支持 ChatGPT 订阅配额。':'仅查询官方余额；Token 用量需由你的程序上报或导入。'}</p></div>`).join('');
}
function table(){const start=page*15,rows=data.events.slice(start,start+15);$('events').innerHTML=rows.length?rows.map(r=>`<tr><td>${esc(r.time.slice(0,16).replace('T',' '))}</td><td>${esc(names[r.provider])}<small>${esc(r.model)}</small></td><td>${esc(r.project)}</td><td>${integer(r.input_tokens)}</td><td>${integer(r.output_tokens)}</td><td>${integer(r.cached_tokens)}</td><td>${integer(r.requests)}</td><td>${r.cost===null?'未知':esc(r.currency)+' '+Number(r.cost).toFixed(6)}</td></tr>`).join(''):'<tr><td colspan="8" class="empty">暂无记录。选择其他日期或在真实数据模式导入调用记录。</td></tr>';$('page-info').textContent=`共 ${data.events.length} 条 · 第 ${page+1} / ${Math.max(1,Math.ceil(data.events.length/15))} 页`;$('prev').disabled=page===0;$('next').disabled=start+15>=data.events.length;}
function billing(){const a=data.accounts.openai,b=a.billing;$('official-billing').innerHTML=data.mode==='demo'?'<div class="empty">演示模式不生成官方账单</div>':b?`<div class="budget-value">${Object.entries(b.amounts).map(([c,v])=>esc(c)+' '+Number(v).toFixed(4)).join(' / ')||'0'}</div><p class="muted">${esc(b.start)} 至 ${esc(b.end)}</p><p class="muted">${esc(b.note)}</p>${a.status==='error'||a.billing_error?'<p class="muted">⚠ 当前显示上次成功账单；本次同步未完整成功。</p>':''}`:'<div class="empty">尚无官方费用数据。请配置 Admin Key 后同步。</div>';}
const viewTitles={overview:['总览','每一次调用，都清晰可见。','一个工作空间，掌握所有模型的用量与成本。'],details:['用量明细','从总量，看到每一笔调用。','按模型、项目与平台，追踪你的 API 使用情况。'],billing:['费用与预算','让每一份预算，都有依据。','区分官方费用与估算，清楚掌握已知成本。'],settings:['账户与接入','连接你的 AI 工作空间。','密钥在本机配置，账户数据在服务端同步。']};
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{currentView=b.dataset.view;document.querySelectorAll('.view').forEach(v=>v.hidden=v.id!==currentView);document.querySelectorAll('nav button').forEach(n=>n.classList.toggle('active',n.dataset.view===currentView));const t=viewTitles[currentView];$('crumb').textContent=t[0];$('title').textContent=t[1];$('subtitle').textContent=t[2];}));
['live','provider','source','start','end','model','project'].forEach(id=>$(id).addEventListener('change',()=>{if(['live','source'].includes(id)){$('model').value='all';$('project').value='all';}load();}));
$('prev').onclick=()=>{page--;table();};$('next').onclick=()=>{page++;table();};
$('export').onclick=()=>{location.href='/api/export?'+params();};
$('sync').onclick=async()=>{if(!$('live').checked)return;const b=$('sync');b.disabled=true;b.textContent='⟳ 正在同步…';try{const r=await api('/api/sync',{});toast(r.busy?'已有同步任务进行中，请稍后刷新':'同步已完成，请查看各平台状态');await load();}catch(e){toast(e.message);}finally{b.textContent='⟳ 同步数据';b.disabled=!$('live').checked;}};
$('budget-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/budget',{amount:$('budget-input').value});toast('预算已保存到本机');await load();}catch(e){toast(e.message);}};
$('import-file').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>1900000)throw Error('文件需小于 1.9 MB');const parsed=JSON.parse(await file.text()),r=await api('/api/events',{events:Array.isArray(parsed)?parsed:parsed.events});toast(`导入成功：新增 ${r.inserted} 条，重复记录已跳过`);await load();}catch(err){toast(err.message);}finally{e.target.value='';}};
load();setInterval(()=>{if(!$('sync').disabled||!$('live').checked)load();},60000);
