import {api} from './client.js';
export const sourcesApi={list:()=>api('/sources'),create:data=>api('/sources',{method:'POST',body:JSON.stringify(data)}),update:(id,data)=>api('/sources/'+id,{method:'PUT',body:JSON.stringify(data)}),records:id=>api('/sources/'+id+'/records'),add:(id,records)=>api('/sources/'+id+'/records',{method:'POST',body:JSON.stringify({records})})};
export const runsApi={list:()=>api('/runs'),get:id=>api('/runs/'+id),create:data=>api('/runs',{method:'POST',body:JSON.stringify(data)})};
export const arrivalsApi={
  list:()=>api('/arrivals'),
  get:id=>api('/arrivals/'+id),
  targets:sourceId=>api('/arrivals/targets?source_id='+sourceId),
  create:data=>api('/arrivals',{method:'POST',body:JSON.stringify(data)}),
  notes:()=>api('/arrival-notes'),
  createNote:data=>api('/arrival-notes',{method:'POST',body:JSON.stringify(data)}),
  approveNote:id=>api('/arrival-notes/'+id+'/approve',{method:'POST'})
};
export const notesApi={list:()=>api('/notes'),create:data=>api('/notes',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/notes/'+id+'/approve',{method:'POST'})};
