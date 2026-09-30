
def total_boxes(pallets):
    return sum(pallets)


def occupied_cells(pallets):
    return len(pallets)


def ship_boxes(pallets, requested):#списание товара со склада. Сначала забираем товары с последней паллеты. 
    
    if type(requested) is not int or requested < 0:
        raise ValueError("Количество должно быть целым и неотрицательным")

    result = pallets.copy()
    shipped = min(requested, total_boxes(result))
    remaining = shipped

    while remaining > 0:
        taken = min(remaining, result[-1])
        result[-1] -= taken
        remaining -= taken
        if result[-1] == 0:
            result.pop()

    return result, shipped, requested - shipped


def process_orders(stock, orders):#список операций и обновление состояния склада
    operations = []
    for order in orders:
        for line in order["lines"]:
            sku = line["sku"]
            pallets, shipped, unfulfilled = ship_boxes(stock[sku]["pallets"], line["boxes"])
            stock[sku]["pallets"] = pallets
            operations.append({
                "date": order["date"],
                "order_id": order["order_id"],
                "sku": sku,
                "zone": stock[sku]["zone"],
                "requested_boxes": line["boxes"],
                "shipped_boxes": shipped,
                "unfulfilled_boxes": unfulfilled,
            })
    return operations
