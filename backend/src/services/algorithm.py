from collections import Counter
import hashlib,json
from .domain_validation import validate_parameters
def calculate(records,parameters):
    p=validate_parameters(parameters);edges=Counter();outgoing=Counter();incoming=Counter();sessions=set()
    for r in records:
        v=r['values'];sid=v['session']
        if sid in sessions:raise ValueError('会话编号重复，请将一个完整会话保存在同一行')
        sessions.add(sid);path=[s.strip() for s in v['path'].split('>')]
        for a,b in zip(path,path[1:]):edges[a,b]+=1;outgoing[a]+=1;incoming[b]+=1
    total=sum(edges.values())
    if total==0:raise ValueError('没有相邻章节转移；单章会话不形成接续边')
    rows=[]
    for (a,b),count in edges.items():
        if count<p['min_count']:continue
        prob=count/outgoing[a];base=incoming[b]/total
        rows.append({'from':a,'to':b,'count':count,'conditional_probability':prob,'target_base_rate':base,'lift':prob/base,'support':count/total})
    rows.sort(key=lambda r:(-r['lift'],-r['count'],r['from'],r['to']));rows=rows[:p['top_n']]
    return {'summary':[{'label':'独立会话','value':len(records)},{'label':'有效接续边','value':total},{'label':'达标规则','value':len(rows)},{'label':'章节数','value':len(set(outgoing)|set(incoming))}], 'rows':rows,'columns':['from','to','count','conditional_probability','target_base_rate','lift','support'],'chart':[{'label':r['from']+' → '+r['to'],'value':r['lift']} for r in rows[:12]],'target_counts':dict(incoming),'outgoing_counts':dict(outgoing),'explanation':'P(下一章=b | 当前章=a)=边a→b次数/从a出发总次数；目标基率=所有接续边中到达b次数/总边数；提升度=条件概率/目标基率。无跨会话拼接，无因果推断。','checksum':hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest(),'seed':42}
