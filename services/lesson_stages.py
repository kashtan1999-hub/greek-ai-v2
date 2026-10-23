"""Durable stage boundaries use the existing stored exercise IDs."""
def build_stages(count):
    if count<5: raise ValueError('At least five questions are required for practice, check and quiz')
    return [{'name':'mini','start':0,'end':2}, {'name':'understanding','start':2,'end':4}, {'name':'quiz','start':4,'end':count}]

def stage_at(plan,index=None):
    index=int(plan.get('index',0) if index is None else index)
    return next((s for s in plan.get('stages',[]) if s['start']<=index<s['end']),None)

def eligible_to_advance(plan,percentage):
    if plan.get('mistake_review') or plan.get('return_to'): return False
    if not plan.get('stages'): return percentage>=80 and not plan.get('hints_used',False)  # in-flight legacy test
    scores=plan.get('stage_scores',{})
    return scores.get('mini',0)>=2 and scores.get('understanding',0)>=2 and percentage>=80 and not plan.get('quiz_hint_used',False)
