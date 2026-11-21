"""Independent arithmetic for the synthetic buyer exercise. No engine imports."""
from math import inf

def mortgage(principal, rate, term):
    if rate == 0:
        return principal / term
    rate_month = rate / 12
    return principal / sum((1 + rate_month) ** -month for month in range(1, term + 1))

def balance(principal, rate, term, after):
    payment = mortgage(principal, rate, term)
    for _ in range(min(after,term)):
        principal = principal * (1 + rate/12) - payment
    return max(0.,principal)

def positive(x): return max(x,0.)

def calculate(*,price,deposit,lmi,liquid,acquisition,normal,lean,holding,insurance,rate,term,incomes,capex,locked,redundancy,leave,dip,limit,death,tpd):
    principal = price - deposit + lmi
    M = mortgage(principal, rate, term)
    Mstress = mortgage(principal, rate + .015, term)
    income = sum(incomes)
    remaining = income - max(incomes)
    day2 = liquid - deposit - acquisition
    base = M + lean + holding
    stressed = Mstress + lean + holding
    sa = income - stressed - insurance * .20 / 12
    repair = max(capex * 1.25,15000)
    normal_surplus = income - M - normal - holding
    c3, c12 = (day2 + m*sa - repair for m in (3,12))
    target = income - lean - holding
    low,high=0,2
    for _ in range(65):
        mid = (low+high) / 2
        if mortgage(principal,mid,term) < target: low = mid
        else: high = mid
    gap = positive(base + locked - remaining)
    runway = (day2 + redundancy + leave)/gap if gap else inf
    l24 = balance(principal,rate,term,24)
    price24 = price*(1-dip)
    sales_costs = .025*price24 + 3500
    equity = price24 - sales_costs - l24
    c24 = day2 + 24*normal_surplus - capex
    loss = (deposit+acquisition-equity)/liquid if liquid else None
    return locals()

def first_failure_rate(principal,term,budget):
    if mortgage(principal,0,term)>budget: return None
    lo,hi=0,2
    for _ in range(65):
        mid=(lo+hi)/2
        if mortgage(principal,mid,term)>budget: hi=mid
        else: lo=mid
    return lo

def evaluate(p):
    a = calculate(price=p['purchase_price'],deposit=p['deposit'],lmi=p['capitalized_lmi'],liquid=p['cash_before_settlement'],acquisition=p['acquisition_costs'],normal=p['normal_living_monthly'],lean=p['lean_living_monthly'],holding=p['property_costs_monthly'],insurance=p['insurance_annual'],rate=p['annual_rate_decimal'],term=p['term_months'],incomes=p['earner_incomes_monthly'],capex=p['first_year_works'],locked=p['locked_commitments_monthly'],redundancy=p['redundancy_available'],leave=p['leave_available'],dip=.15 if p['illiquid'] else .10,limit=p['loss_duration_months'],death=p['death_cover'],tpd=p['tpd_cover'])
    get=a.__getitem__
    facts=[p[k] for k in ('insurable','primary_works_approved','structural_clear')]
    day2,base,sa,c3,c12,stressed,gap,runway,equity,c24,loss,limit,principal,price,normal_surplus=map(get,('day2','base','sa','c3','c12','stressed','gap','runway','equity','c24','loss','limit','principal','price','normal_surplus'))
    v_red = False in facts or day2 < 2*base or day2-p['urgent_works'] < base or a['income'] < base
    v='red' if v_red else 'unresolved' if None in facts else 'green'
    rstar=first_failure_rate(principal,p['term_months'],a['income']-p['lean_living_monthly']-p['property_costs_monthly'])
    A='red' if min(c3,c12)<0 or rstar is None or (rstar-p['annual_rate_decimal'] < .015-1e-9) else 'green' if min(c3-stressed,c12-3*stressed,sa,sa+p['lean_living_monthly']-p['normal_living_monthly'])>=0 else 'amber'
    B='red' if runway<limit else 'amber' if runway < limit+2 or (gap and day2/gap<p['ip_wait_months']) or min(p['death_cover'],p['tpd_cover']) < .8*principal else 'green'
    firstneg=min(day2,day2+11*normal_surplus,day2+12*normal_surplus-p['first_year_works'],c24)<0
    C='red' if equity+c24<0 or firstneg or loss>.75 else 'amber' if loss>=.4 or a['l24']/a['price24'] >.8 else 'green'
    grades=dict(V=v,A=A,B=B,C=C)
    state=next(s for s in ['red','unresolved','amber','green'] if s in grades.values())
    fields=['principal','M','Mstress','day2','base','stressed','sa','normal_surplus','c3','c12','repair','remaining','gap','runway','l24','price24','sales_costs','equity','c24','loss']
    vals={k:(round(a[k],8) if a[k]!=inf else 'unbounded') for k in fields}
    vals.update(wealth_exit=round(equity+c24,8),rstar=rstar,after_urgent=day2-p['urgent_works'],cover_target=.8*principal)
    return dict(state=state,grades=grades,amounts=vals)

def reprice(p,policy,price):
    opts=policy['deposit']
    deposit=opts['value'] * (price if opts['mode']=='ratio' else 1)
    row=next(c for c in policy['costs'] if price<=c['up_to_price'])
    fees=sum(row[k]['fixed']+row[k]['price_ratio']*price for k in ('duty','acquisition'))
    lmi=row['lmi']['fixed']+row['lmi']['loan_ratio']*(price-deposit)
    return dict(p,purchase_price=price,deposit=deposit,acquisition_costs=fees,capitalized_lmi=lmi)

def bid(p,policy):
    grid=range(policy['min_price'],policy['max_price']+1,policy['increment'])
    results={b:evaluate(reprice(p,policy,b))['state'] for b in grid}
    feasible=[b for b,s in results.items() if s in ('amber','green')]
    return max(feasible,default=None),results

if __name__=='__main__':
    from pathlib import Path
    import json,sys
    dest=Path(__file__).resolve().parent
    buyers=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
    result={}
    for buyer in buyers:
        p=buyer['profile']
        result[buyer['id']]=r=evaluate(p)
        r['ceiling'],r['grid']=bid(p,buyer['bid_policy'])
        print(buyer['id'],r['state'],r['grades'],r['ceiling'],r['amounts']['equity'],r['amounts']['base'])
    (dest/'expected.json').write_text(json.dumps(result,indent=2))


