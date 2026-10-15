import random
from datetime import datetime, time, timedelta

from config import (DEADLINE_OFFSETS, DEADLINE_WEIGHTS,
                    ORDER_START_MINUTE, ORDER_END_MINUTE)


def generate_orders(day, skus, seed):#генерация заказов с временем поступления и крайним сроком отправки
    if len(skus) < 2 or len(set(skus)) != len(skus):
        raise ValueError("Нужны минимум два различных SKU")

    rng = random.Random(seed + day.toordinal())
    # Отдельное зерно для сроков сохраняет прежний поток SKU и количеств.
    time_rng = random.Random(seed + day.toordinal() + 1_000_000)
    orders = []
    for number in range(1, rng.randint(9, 13) + 1):
        total = rng.randint(8, 15)
        selected = rng.sample(list(skus), rng.randint(1, 2))
        if len(selected) == 1:
            lines = [{"sku": selected[0], "boxes": total}]
        else:
            first = rng.randint(3, total - 3)
            lines = [
                {"sku": selected[0], "boxes": first},
                {"sku": selected[1], "boxes": total - first},
            ]
        minute = time_rng.randint(ORDER_START_MINUTE, ORDER_END_MINUTE)
        created_at = datetime.combine(day, time(minute // 60, minute % 60))
        offset = time_rng.choices(DEADLINE_OFFSETS, weights=DEADLINE_WEIGHTS, k=1)[0]
        orders.append({
            "order_id": f"{day.isoformat()}-O{number:03d}",
            "date": day.isoformat(),
            "created_at": created_at.isoformat(),
            "deadline": (day + timedelta(days=offset)).isoformat(),
            "lines": lines,
        })
    return orders


def request_rng(seed, identifier):#отдельное воспроизводимое зерно запросов изменения заказа
    import hashlib
    value = f'{seed}|order_requests|{identifier}'.encode('utf-8')
    return random.Random(int.from_bytes(hashlib.sha256(value).digest(), 'big'))


def generate_request_slots(day, seed, settings):#1–2 запроса на календарную неделю с понедельника по воскресенье
    if not settings['ORDER_CHANGES_ENABLED']:
        return []
    monday = day - timedelta(days=day.weekday())
    rng = request_rng(seed, monday.isoformat())
    count = rng.randint(*settings['ORDER_REQUESTS_PER_WEEK'])
    days = sorted(rng.sample(range(7), count))
    slots = []
    for index, offset in enumerate(days, 1):
        minute = rng.randint(settings['ORDER_REQUEST_START_MINUTE'], settings['ORDER_REQUEST_END_MINUTE'])
        action = rng.choice(('cancel', 'change_quantity'))
        event_day = monday + timedelta(days=offset)
        if event_day == day:
            slots.append(dict(request_id=f'{monday.isoformat()}-C{index}',
                timestamp=(datetime.combine(day, time())+timedelta(minutes=minute)).isoformat(),
                action=action))
    return slots


def generate_order_request(slot, orders, seed, settings):#выбор уже поступившего заказа и новых количеств одной строки
    rng = request_rng(seed, slot['request_id'])
    eligible = [order for order in orders if any(line['unpicked_boxes'] > line['picking_boxes'] for line in order['lines'])]
    candidates = sorted(eligible or orders, key=lambda order: order['order_id'])
    request = dict(slot, order_id='', sku='', new_boxes='')
    if not candidates:
        return request
    order = rng.choice(candidates)
    request['order_id'] = order['order_id']
    if slot['action'] == 'change_quantity':
        eligible_lines = [line for line in order['lines'] if line['unpicked_boxes'] > line['picking_boxes']]
        line = rng.choice(eligible_lines or order['lines'])
        delta = rng.randint(*settings['ORDER_CHANGE_BOXES']) * rng.choice((-1, 1))
        request['sku'] = line['sku']
        request['new_boxes'] = max(1, line['ordered_boxes']-line['cancelled_boxes']+delta)
    return request
