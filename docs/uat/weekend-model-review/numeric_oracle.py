"""Independent scalar oracles for Weekend Offer model verification. Synthetic amounts."""
from decimal import Decimal as Z, localcontext

ZERO = Z(0)
ONE = Z(1)


def number(x):
    return Z(str(x))


def installment(principal, annual, months):
    with localcontext() as ctx:
        ctx.prec = 44
        principal, annual, months = map(number, (principal, annual, months))
        q = annual / 12
        if q == 0:
            return principal / months
        return principal * q / (1 - (1 + q) ** (-months))


def loan_at(principal, annual, months, elapsed):
    # Iterative ledger, independent of direct balance formula used by many solvers.
    debt, annual = map(number, (principal, annual))
    installment_ = installment(principal, annual, months)
    for month in range(min(months, elapsed)):
        debt += debt * annual / 12 - installment_
    return max(debt, ZERO)


def cash_ledger(opening, net_ordinary, n, debits=None):
    balance = number(opening)
    out = [balance]
    for m in range(1, n + 1):
        balance += number(net_ordinary)
        balance -= number((debits or {}).get(m, 0))
        out.append(balance)
    return out


def forced_sale(price, debt, annual, months, day2, monthly_net, repairs,
                deposit, acquisition, pre_purchase_wealth, fall, elapsed):
    value = number(price) * (1-number(fall))
    balance = loan_at(debt, annual, months, elapsed)
    equity = value * number(.975) - 3500 - balance
    cash = cash_ledger(day2, monthly_net, elapsed)[-1] - number(repairs)
    return dict(value=value, balance=balance, equity=equity, cash=cash,
                net_wealth=equity+cash, lvr=balance/value,
                loss=(number(deposit)+number(acquisition)-equity)/number(pre_purchase_wealth))


def max_eligible_grid(prices, statuses):
    known = [p for p, s in zip(prices, statuses) if s in ('green','amber')]
    unknown = [p for p, s in zip(prices, statuses) if s == 'unknown']
    high = max(known) if known else None
    unresolved = any(high is None or p > high for p in unknown)
    return high, unresolved
