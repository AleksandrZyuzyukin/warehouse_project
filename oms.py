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
