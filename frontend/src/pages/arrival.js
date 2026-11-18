import {domain} from '../constants/domain.js';
import {research} from '../stores/research.js';
import {session} from '../stores/session.js';
import {arrivalsApi} from '../api/research.js';
import {download} from '../api/client.js';
import {sourceOptions} from '../components/common/business.js';
import {table} from '../components/common/table.js';
import {arrivalStates,arrivalClassLabels} from '../constants/enums.js';
import {esc,fmt} from '../utils/format.js';
import {bind,action,toast} from '../hooks/actions.js';

function arrivalStatus(state){
  return '<span class="status '+esc(state)+'">'+esc(arrivalStates[state]||state)+'</span>';
}
function ledger(runs){
  if(!runs.length)return '<div class="empty">还没有终章到达研究。</div>';
  return '<div class="ledger">'+runs.slice(0,10).map(r=>'<a href="#arrival" data-arrival="'+r.id+'"><small>#'+r.id+'</small><strong>'+esc(r.name)+' · 目标 '+esc(r.target_chapter)+'</strong>'+arrivalStatus(r.state)+'<time>'+r.iterations+' 轮 · 上界 '+(r.error_bound?Number(r.error_bound).toExponential(1):'—')+'</time></a>').join('')+'</div>';
}
function basis(result){
  if(!result)return '';
  return '<aside class="method-sheet"><p class="eyebrow">PROBABILITY BASIS</p><h2>概率依据与可核验误差</h2><p>'+esc(result.explanation)+'</p><ul class="basis-list">'
    +'<li>目标章：<b>'+esc(result.target_chapter)+'</b>（到达即概率 1）</li>'
    +'<li>收敛判据：全部章节绝对误差上界 &lt; '+fmt(result.tolerance)+'</li>'
    +'<li>本次报告误差上界：<b>'+Number(result.error_bound).toExponential(2)+'</b></li>'
    +'<li>Bellman 相邻轮残差：'+Number(result.bellman_residual).toExponential(2)+'</li>'
    +'<li>完整迭代轮数（半轮不计数）：'+result.iterations+'</li>'
    +'<li>输入 SHA256：<code>'+esc(result.checksum)+'</code></li></ul>'
    +'<h3>结构分类口径</h3><p class="fine">'+Object.entries(result.classification_legend).map(([k,v])=>esc(arrivalClassLabels[k]||k)+'：'+esc(v)).join('<br>')+'</p></aside>';
}
export async function arrivalPage(){
  const run=research.arrivalId?await arrivalsApi.get(research.arrivalId):null;
  research.activeArrival=run;
  const result=run?.result;
  const converged=result?.converged===true && result.error_bound<domain.arrival_tolerance;
  return '<section class="page-heading"><p class="eyebrow">05 / TERMINAL CHAPTER ARRIVAL</p><h1>一步接得高，不等于读得到终章。</h1><p>'+esc(domain.arrival_method_label)+'。原一步接续研究仍在“完整结果”中可读，两者独立冻结、独立求解。</p></section>'
    +'<label class="compact">终章任务<select id="arrival-select">'+(research.arrivals.length?research.arrivals.map(r=>'<option value="'+r.id+'" '+(r.id===research.arrivalId?'selected':'')+'>'+esc(r.name)+' · #'+r.id+' · '+esc(r.target_chapter)+'</option>').join(''):'<option value="">暂无任务</option>')+'</select></label>'
    +(run?'<div class="run-title"><h2>'+esc(run.name)+'</h2>'+arrivalStatus(r.state)+'<small>#'+run.id+' · 目标章：'+esc(r.target_chapter)+' · 来源 #'+r.source_id+' · 冻结 '+r.snapshot.records.length+' 条会话</small>'+(converged?'<button id="export-arrival" class="secondary">下载终章概率 CSV ↗</button>':'')+'</div>'
      +(r.state==='failed'?'<div class="failure"><h2>本次终章研究未给出可用结果</h2><p>'+esc(r.error)+'</p><p class="fine">已完成的完整迭代与检查点保留；可在同目标、同冻结输入下重新入队续算，或新建研究改目标从零求解。</p></div>':
        !result?'<div class="pending"><span class="spinner"></span><h2>'+(r.state==='queued'?'排队等待：任务已冻结，等待 worker 领取':'分批求解中：分块 Jacobi 迭代进行')+'</h2><p>已完成完整迭代 <b id="arrival-iters">'+r.iterations+'</b> 轮；最近误差上界 <b id="arrival-bound">'+(r.error_bound?Number(r.error_bound).toExponential(2):'—')+'</b>。页面自动刷新，中断后按同批输入与检查点续算，半轮更新不会混入。</p></div>':
        converged?'<p class="fine">求解参数：'+esc(JSON.stringify(r.parameters))+'</p><div class="result-grid"><section><h2>收敛摘要</h2><dl class="metrics">'+result.summary.map(x=>'<div><dt>'+esc(x.label)+'</dt><dd>'+fmt(x.value)+'</dd></div>').join('')+'</dl></section>'+basis(result)+'</div>'
          +'<h2>各章“先到目标再退出”概率 <small>共 '+result.rows.length+' 章，预览前30行；CSV 含全部原始数值（全精度）</small></h2>'
          +table(result.rows.map(x=>({
            ...x,
            hit_probability:x.hit_probability.toFixed(6),
            error_bound:x.error_bound===0?'0（结构精确）':x.error_bound.toExponential(2),
            exit_estimate:x.exit_estimate.toFixed(4),
            classification:arrivalClassLabels[x.classification]||x.classification,
            in_cycle:x.in_cycle?'是':'否'
          })),result.columns.map(c=>({key:c,label:domain.column_labels[c]||arrivalClassLabels[c]||c})),{limit:30})
          +'<p><a class="text-link" href="#arrival-notes">仅据收敛结果提交编辑衔接建议 ↗</a></p>'
        :'<div class="failure"><h2>结果未达收敛标准</h2><p>误差上界 '+Number(result.error_bound).toExponential(2)+' 未低于 '+fmt(domain.arrival_tolerance)+'，不提供概率导出与建议。</p></div>')
      :'<p class="empty">还没有终章任务，请在右侧指定目标章并冻结求解。</p>')
    +'<div class="split config-split ledger-head"><section>'+(run?'<h2>其他终章任务</h2>'+ledger(research.arrivals):ledger(research.arrivals))+'</section><aside class="entry-sheet"><h2>新建终章到达研究</h2>'+createForm()+'</aside></div>';
}
function createForm(){
  if(!session.writable)return '<p>阅读者可以查看已收敛任务；新建终章研究由分析师或负责人执行。</p>';
  return '<form id="arrival-form"><label>分析来源<select name="source_id" id="arrival-source">'+sourceOptions(research.sources,research.sourceId)+'</select></label>'
    +'<label>研究名称<input name="name" required value="终章到达复核研究"></label>'
    +'<label>目标章<select name="target_chapter" id="arrival-target"><option value="">先选择来源加载章节…</option></select></label>'
    +'<p class="fine">目标必须是冻结会话中出现过的章节。提交即冻结来源与全部会话；改目标需新建任务，绝不复用旧求解进度。</p><button type="submit">冻结输入并求解 →</button></form>';
}
export function bindArrival(refresh){
  bind('#arrival-select','change',async e=>{research.arrivalId=Number(e.target.value);await refresh()});
  const loadTargets=async sourceId=>{
    const sel=document.querySelector('#arrival-target');
    if(!sel)return;
    try{const {targets}=await arrivalsApi.targets(Number(sourceId));
      sel.innerHTML=targets.map(t=>'<option value="'+esc(t)+'">'+esc(t)+'</option>').join('');
    }catch(err){toast(err.message,true)}
  };
  bind('#arrival-source','change',e=>loadTargets(e.target.value));
  // 表单首次渲染即加载默认来源的章节，避免空目标下拉
  const src=document.querySelector('#arrival-source');
  if(src)loadTargets(src.value);
  action('#arrival-form',async form=>{
    const fd=new FormData(form);
    const r=await arrivalsApi.create({source_id:Number(fd.get('source_id')),name:fd.get('name'),target_chapter:fd.get('target_chapter')});
    research.arrivalId=r.id;location.hash='arrival';await refresh();
  });
  bind('#export-arrival','click',async()=>{try{await download('/arrivals/'+research.arrivalId+'/export','arrival-'+research.arrivalId+'.csv')}catch(e){toast(e.message,true)}});
}
