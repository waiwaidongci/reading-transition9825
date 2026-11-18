import {domain} from '../constants/domain.js';
import {research} from '../stores/research.js';
import {session} from '../stores/session.js';
import {arrivalsApi} from '../api/research.js';
import {download} from '../api/client.js';
import {status} from '../components/common/status.js';
import {reviewStates} from '../constants/enums.js';
import {esc,formObject} from '../utils/format.js';
import {action,toast} from '../hooks/actions.js';

// 仅列出已收敛（误差上界 < 1e-6）的终章任务；未收敛任务不出现在建议来源中
function convergedOptions(){
  const ok=research.arrivals.filter(r=>r.state==='completed');
  if(!ok.length)return '<option value="">暂无可采用的收敛结果</option>';
  return ok.map(r=>'<option value="'+r.id+'" '+(r.id===research.arrivalId?'selected':'')+'>'+esc(r.name)+' · #'+r.id+' · 目标 '+esc(r.target_chapter)+'</option>').join('');
}
export function arrivalNotesPage(){
  return '<section class="page-heading"><p class="eyebrow">06 / ARRIVAL EDITORIAL PLAN</p><h1>终章编辑衔接建议，只采用收敛结果。</h1><p>误差上界未低于百万分之一的任务不可作为建议依据；建议创建时冻结收敛概率快照，负责人批准后方可导出。原一步研究的建议流程保持不变。</p></section>'
    +'<div class="split"><section class="notes-ledger">'+(research.arrivalNotes.length?research.arrivalNotes.map(n=>'<article class="note-record"><header>'+status(n.state)+'<small>终章任务 #'+n.arrival_run_id+'</small></header><h2>'+esc(n.title)+'</h2><p>'+esc(n.body)+'</p><footer><small>'+esc(n.author)+(n.approved_by?' · 批准 '+esc(n.approved_by):'')+'</small>'+(n.state==='draft'&&session.user.role==='admin'?'<button data-arrival-approve="'+n.id+'">批准终章建议 ✓</button>':'')+(n.state==='approved'?'<button class="secondary" data-arrival-note-export="'+n.id+'">下载批准快照 CSV ↗</button>':'')+'</footer></article>').join(''):'<div class="empty">还没有终章编辑衔接建议。仅可基于已收敛（误差上界 &lt; 1e-6）的终章研究创建。</div>')+'</section>'
    +'<aside class="entry-sheet">'+(session.writable?'<h2>新增终章编辑建议</h2><form id="arrival-note-form"><label>采用的收敛结果<select name="arrival_run_id">'+convergedOptions()+'</select></label><label>建议标题<input name="title" required value="终章衔接复核意见"></label><label>业务解释与下一步<textarea name="body" required rows="6">已核对误差上界低于 1e-6，本建议仅基于该收敛概率快照；业务行动需结合现场记录。</textarea></label><button type="submit">保存建议草案 →</button></form>':'<h2>批准快照交付</h2><p>阅读者只能阅读与下载。未批准草案显示“待复核”，不能下载批准快照。</p>')+'</aside></div>';
}
export function bindArrivalNotes(refresh){
  action('#arrival-note-form',async form=>{
    const data=formObject(form);
    if(!data.arrival_run_id){toast('暂无可采用的收敛结果',true);return}
    await arrivalsApi.createNote({...data,arrival_run_id:Number(data.arrival_run_id)});
    await refresh();toast('终章编辑建议已冻结为草案（仅采用收敛结果）');
  });
  for(const b of document.querySelectorAll('[data-arrival-approve]'))b.onclick=async()=>{try{await arrivalsApi.approveNote(b.dataset.arrivalApprove);await refresh();toast('负责人已批准终章建议')}catch(e){toast(e.message,true)}};
  for(const b of document.querySelectorAll('[data-arrival-note-export]'))b.onclick=async()=>{try{await download('/arrival-notes/'+b.dataset.arrivalNoteExport,'arrival-approved-'+b.dataset.arrivalNoteExport+'.csv')}catch(e){toast(e.message,true)}};
}
