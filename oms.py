import random


def generate_orders(day, skus, seed):
    if len(skus) < 2 or len(set(skus)) != len(skus):
        raise ValueError("Нужны минимум два различных SKU")

    # Дата влияет на поток, но одинаковые дата и seed дают одинаковые заказы.
    rng = random.Random(seed + day.toordinal())
    orders = []

    for number in range(1, rng.randint(9, 13) + 1):
        total = rng.randint(8, 15)#общее число коробок в заказе
        selected = rng.sample(list(skus), rng.randint(1, 2))#список выбранных товаров для заказа
        if len(selected) == 1:
            lines = [{"sku": selected[0], "boxes": total}]
        else:
            first = rng.randint(3, total - 3)#кол-во первого товара
            lines = [
                {"sku": selected[0], "boxes": first},
                {"sku": selected[1], "boxes": total - first},
            ]

        orders.append({
            "order_id": f"{day.isoformat()}-O{number:03d}",
            "date": day.isoformat(),
            "lines": lines,
        })

    return orders
