from pathlib import Path
import csv, json
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parent

def read(name):
    with (ROOT / 'structured' / (name + '.csv')).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

counts = {'customers': 20, 'contracts': 40, 'projects': 60, 'departments': 6, 'project_financials': 300, 'documents': 70, 'document_projects': 75}
data = {k:read(k) for k in counts}
for k,v in data.items():
    assert len(v)==counts[k], (k,len(v))
keys = {'customers':'customer_id','contracts':'contract_id','projects':'project_id','departments':'department_id','project_financials':'financial_id','documents':'document_id'}
ids = {}
for name,key in keys.items():
    rows=data[name]; ids[name]={r[key] for r in rows}
    assert len(ids[name])==len(rows) and '' not in ids[name], name
for name,key,target in [('contracts','customer_id','customers'),('projects','contract_id','contracts'),('projects','department_id','departments'),('project_financials','project_id','projects'),('document_projects','document_id','documents'),('document_projects','project_id','projects')]:
    assert all(r[key] in ids[target] for r in data[name]), (name,key)
pairs=[(r['project_id'],r['period_month']) for r in data['project_financials']]
assert len(set(pairs))==300
assert set(pairs)=={(p,f'2026-{m:02d}-01') for p in ids['projects'] for m in range(6,11)}
assert all(int(r[k])>=0 for r in data['project_financials'] for k in ['revenue_vnd','direct_cost_vnd'])
project_contract={r['project_id']:r['contract_id'] for r in data['projects']}
revenue=defaultdict(int)
for r in data['project_financials']: revenue[project_contract[r['project_id']]]+=int(r['revenue_vnd'])
assert all(revenue[r['contract_id']]<=int(r['contract_value_vnd']) for r in data['contracts'])
links=[(r['document_id'],r['project_id']) for r in data['document_projects']]
assert len(set(links))==len(links)
for d in data['documents']:
    path=ROOT / d['relative_path']; assert path.is_file() and d['document_id'] in path.read_text(encoding='utf-8')
    assert (d['document_type']=='policy') == (not any(a==d['document_id'] for a,b in links))
q=json.loads((ROOT/'evaluation'/'golden_questions.json').read_text(encoding='utf-8'))
assert len(q)==50 and len({x['question_id'] for x in q})==50 and all(x['evidence'] and x['expected_answer'] for x in q)
# Verify numeric KPIs against raw data and graph IDs against joins.
def agg(p=None,m=None):
    rows=[r for r in data['project_financials'] if (p is None or r['project_id']==p) and (m is None or r['period_month']==m)]
    rev=sum(int(r['revenue_vnd']) for r in rows); cost=sum(int(r['direct_cost_vnd']) for r in rows);return rev,cost,rev-cost
v={x['question_id']:x['expected_values'] for x in q}
assert v['Q01']['revenue_vnd']==agg('PRJ001','2026-10-01')[0]
assert v['Q02']['direct_cost_vnd']==agg('PRJ003')[1]
assert v['Q03']['gross_profit_vnd']==agg(m='2026-10-01')[2]
assert v['Q04']=={'october_vnd':agg(m='2026-10-01')[0],'september_vnd':agg(m='2026-09-01')[0],'delta_vnd':agg(m='2026-10-01')[0]-agg(m='2026-09-01')[0]}
r,c,p=agg('PRJ007','2026-10-01');assert v['Q05']=={'gross_margin_pct':None,'revenue_vnd':r,'gross_profit_vnd':p} and r==0
assert v['Q19']=={'revenue_vnd':r,'direct_cost_vnd':c}
pc={r['contract_id']:r['customer_id'] for r in data['contracts']}
assert set(v['Q11']['project_ids'])=={r['project_id'] for r in data['projects'] if r['contract_id']=='HD001'}
assert v['Q12']=={'contract_id':project_contract['PRJ003'],'customer_id':pc[project_contract['PRJ003']]}
assert set(v['Q13']['project_ids'])=={r['project_id'] for r in data['projects'] if r['department_id']=='DEP002'}
assert set(v['Q14']['project_ids'])=={p for p,c in project_contract.items() if pc[c]=='CUS001'}
assert set(v['Q15']['document_ids'])=={a for a,b in links if b=='PRJ001'}
assert v['Q16']['contract_id']==project_contract['PRJ001']
assert v['Q17']['customer_id']==pc[project_contract['PRJ007']]
assert v['Q18']['contract_id']==project_contract['PRJ002']
# New checks, computed independently by SQL on an in-memory copy, never connects to company DB.
import sqlite3
conn=sqlite3.connect(':memory:')
for name,rows in data.items():
    fields=list(rows[0]); types=['INTEGER' if k.endswith('_vnd') else 'TEXT' for k in fields]
    conn.execute('CREATE TABLE '+name+' ('+', '.join(k+' '+t for k,t in zip(fields,types))+')')
    conn.executemany('INSERT INTO '+name+' VALUES ('+','.join('?' for _ in fields)+')',[[r[k] for k in fields] for r in rows])
checks=json.loads((ROOT/'evaluation'/'reference_checks.json').read_text(encoding='utf-8'))
for qid,spec in checks.items():
    for key,check in spec.items():
        result=conn.execute(check['sql']).fetchall()
        actual=[r[0] for r in result] if check.get('many') else result[0][0]
        expected=v[qid][key]
        assert (sorted(actual)==sorted(expected) if check.get('many') else actual==expected),(qid,key,actual,expected)
assert {b for a,b in links}==ids['projects']
assert len(list((ROOT/'documents').glob('*.md')))==70
assert len({p['project_name'] for p in data['projects']})==60
import re
for question in q:
    for evidence in question['evidence']:
        for did in re.findall(r'\bDOC\d+\b',evidence): assert did in ids['documents'],(question['question_id'],did)
    if question['route']=='insufficient_evidence': assert question['expected_values'] is None
print('PASS: counts, primary/foreign keys, financial periods, document paths, project document coverage, numeric and graph expected values.')
print('Questions by route:',dict(Counter(x['route'] for x in q)))
print('Note: textual RAG answers still need manual review; no live AI or company database was tested.')
