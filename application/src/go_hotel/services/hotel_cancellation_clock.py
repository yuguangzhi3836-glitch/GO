"""Explicit cancellation clocks. Missing options preserve accepted legacy rules."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def validate_tiers(tiers):
    if not isinstance(tiers,list) or not 1<=len(tiers)<=20:
        raise ValueError('CANCELLATION_TIERS_REQUIRED')
    for tier in tiers:
        if not isinstance(tier,dict) or type(tier.get('fee_basis_points')) is not int or not 0<=tier['fee_basis_points']<=10000:
            raise ValueError('INVALID_CANCELLATION_FEE')
    fees=[t['fee_basis_points'] for t in tiers]
    if fees!=sorted(fees):raise ValueError('ORDERED_COMPLETE_CANCELLATION_TIERS_REQUIRED')
    if 'min_hours' in tiers[0]:
        if any(set(t)!={'min_hours','fee_basis_points'} or type(t['min_hours']) is not int or not 0<=t['min_hours']<=8760 for t in tiers):
            raise ValueError('STRUCTURED_CANCELLATION_TIER_REQUIRED')
        thresholds=[t['min_hours'] for t in tiers]
        if thresholds!=sorted(set(thresholds),reverse=True) or thresholds[-1]!=0:
            raise ValueError('ORDERED_COMPLETE_CANCELLATION_TIERS_REQUIRED')
        return
    if len(tiers)<2 or set(tiers[-1])!={'after_last_deadline','fee_basis_points'} or tiers[-1]['after_last_deadline'] is not True:
        raise ValueError('FINAL_CANCELLATION_DEADLINE_FEE_REQUIRED')
    keys=[]
    for tier in tiers[:-1]:
        if set(tier)!={'days_before_check_in','local_time','fee_basis_points'}:
            raise ValueError('STRUCTURED_CANCELLATION_DEADLINE_REQUIRED')
        days=tier['days_before_check_in']; clock=tier['local_time']
        if type(days) is not int or not 0<=days<=365:
            raise ValueError('INVALID_CANCELLATION_DAYS')
        if not isinstance(clock,str) or len(clock)!=5 or clock[2]!=':':
            raise ValueError('CANCELLATION_TIME_HH_MM_REQUIRED')
        try: parsed=datetime.strptime(clock,'%H:%M')
        except ValueError:raise ValueError('CANCELLATION_TIME_HH_MM_REQUIRED') from None
        if parsed.strftime('%H:%M')!=clock:raise ValueError('CANCELLATION_TIME_HH_MM_REQUIRED')
        keys.append((-days,clock))
    if keys!=sorted(set(keys)):raise ValueError('ORDERED_UNIQUE_CANCELLATION_DEADLINES_REQUIRED')


def local_deadline(check_in,tier,tz_name):
    day=datetime.fromisoformat(check_in).date()-timedelta(days=tier['days_before_check_in'])
    naive=datetime.fromisoformat(day.isoformat()+'T'+tier['local_time'])
    zone=ZoneInfo(tz_name)
    instants=set()
    for fold in (0,1):
        candidate=naive.replace(tzinfo=zone,fold=fold).astimezone(timezone.utc)
        if candidate.astimezone(zone).replace(tzinfo=None)==naive:instants.add(candidate)
    if len(instants)!=1:
        raise ValueError('AMBIGUOUS_OR_NONEXISTENT_CANCELLATION_LOCAL_TIME')
    return instants.pop()


def terms(rules,check_in,boundary,created_at,at,confirmed_at=None):
    anchor=rules.get('cooling_off_anchor','ORDER_CREATED')
    if anchor=='HOTEL_CONFIRMED':
        if confirmed_at is None:raise ValueError('HOTEL_CONFIRMATION_TIME_EVIDENCE_REQUIRED')
        if confirmed_at<created_at or confirmed_at>at:raise ValueError('INVALID_HOTEL_CONFIRMATION_TIME')
        anchor_time=confirmed_at
    elif anchor=='ORDER_CREATED':anchor_time=created_at
    else:raise ValueError('INVALID_COOLING_OFF_ANCHOR')
    end=anchor_time+timedelta(minutes=rules['cooling_off_minutes'])
    cooling=at<end if anchor=='HOTEL_CONFIRMED' else at<min(end,boundary)
    tiers=rules['cancellation_tiers']
    if 'min_hours' in tiers[0]:
        hours=max(0,(boundary-at).total_seconds()/3600)
        fee=next(t['fee_basis_points'] for t in tiers if hours>=t['min_hours'])
        edges=[boundary-timedelta(hours=t['min_hours']) for t in tiers]
    else:
        edges=[local_deadline(check_in,t,rules['timezone']) for t in tiers[:-1]]
        fee=next((tier['fee_basis_points'] for tier,edge in zip(tiers,edges) if at<edge),tiers[-1]['fee_basis_points'])
    return {'fee_basis_points':0 if cooling else fee,'cooling_off_applied':cooling,
        'cooling_end':end,'edges':edges,'anchor':anchor,'anchor_time':anchor_time}
