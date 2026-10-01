from datetime import timedelta

from config import (
    PALLET_CAPACITY, REORDER_POINT, SKU_CELL_CAPACITY,
    SUPPLY_LEAD_DAYS, TARGET_STOCK_POSITION, ZONE_CAPACITY,
)


def total_boxes(pallets):
    return sum(pallets)


def occupied_cells(pallets):
    return len(pallets)


def check_quantity(quantity):
    if type(quantity) is not int or quantity < 0:
        raise ValueError("Количество должно быть целым и неотрицательным")


def ship_boxes(pallets, requested):#списание товара со склада. Сначала забираем товары с последней паллеты. 
    check_quantity(requested)
    result = sorted(pallets, reverse=True)
    shipped = min(requested, total_boxes(result))
    remaining = shipped
    while remaining > 0:
        taken = min(remaining, result[-1])
        result[-1] -= taken
        remaining -= taken
        if result[-1] == 0:
            result.pop()
    return result, shipped, requested - shipped


def receive_boxes(stock, sku, requested):#приёмка товара одного SKU. Сначала заполняем неполные паллеты, затем занимаем свободные ячейки с учётом лимитов SKU и зоны    
    check_quantity(requested)
    item = stock[sku]
    pallets = item["pallets"]
    remaining = requested

    for index in sorted(range(len(pallets)), key=lambda i: pallets[i]):
        accepted = min(remaining, PALLET_CAPACITY - pallets[index])
        pallets[index] += accepted
        remaining -= accepted
        if remaining == 0:
            break

    zone_occupied = sum(len(other["pallets"]) for other in stock.values()
                        if other["zone"] == item["zone"])
    free_cells = min(SKU_CELL_CAPACITY - len(pallets),
                     ZONE_CAPACITY[item["zone"]] - zone_occupied)
    for _ in range(max(0, free_cells)):
        if remaining == 0:
            break
        accepted = min(remaining, PALLET_CAPACITY)
        pallets.append(accepted)
        remaining -= accepted
    pallets.sort(reverse=True)
    return requested - remaining, remaining


def receive_deliveries(stock, supplies, day):#приёмка прибывших поставок. Непринятые коробки оставляем в очереди на следующие дни
    receipts = []
    for supply in supplies:
        if supply["arrival_date"] > day.isoformat():
            continue
        requested = supply["remaining_boxes"]
        accepted, remaining = receive_boxes(stock, supply["sku"], requested)
        supply["remaining_boxes"] = remaining
        receipts.append({
            "date": day.isoformat(), "supply_id": supply["supply_id"],
            "sku": supply["sku"], "zone": stock[supply["sku"]]["zone"],
            "offered_boxes": requested, "accepted_boxes": accepted,
            "unaccepted_boxes": remaining,
        })
    supplies[:] = [supply for supply in supplies if supply["remaining_boxes"] > 0]
    return receipts


def process_orders(stock, orders, day):#обработка заказов от старых к новым. Записываем операции и сохраняем невыполненные части заказов
    operations, pending = [], []
    for order in sorted(orders, key=lambda row: (row["date"], row["order_id"])):
        pending_lines = []
        for line in order["lines"]:
            sku = line["sku"]
            pallets, shipped, unfulfilled = ship_boxes(stock[sku]["pallets"], line["boxes"])
            stock[sku]["pallets"] = pallets
            operations.append({
                "date": day.isoformat(), "order_date": order["date"],
                "order_id": order["order_id"], "sku": sku,
                "zone": stock[sku]["zone"], "requested_boxes": line["boxes"],
                "shipped_boxes": shipped, "unfulfilled_boxes": unfulfilled,
            })
            if unfulfilled:
                pending_lines.append({"sku": sku, "boxes": unfulfilled})
        if pending_lines:
            pending.append({"order_id": order["order_id"], "date": order["date"],
                            "lines": pending_lines})
    return operations, pending


def plan_replenishment(stock, pending, supplies, day):#расчёт позиции запаса. При значении до 240 включительно заказываем пополнение до 420 с учётом спроса и ожидаемых поставок
    requests = []
    for sku, item in stock.items():
        demand = sum(line["boxes"] for order in pending for line in order["lines"]
                     if line["sku"] == sku)
        incoming = sum(supply["remaining_boxes"] for supply in supplies
                       if supply["sku"] == sku)
        physical = total_boxes(item["pallets"])
        position = physical - demand + incoming
        if position <= REORDER_POINT:
            quantity = TARGET_STOCK_POSITION - position
            supply = {
                "supply_id": f"{day.isoformat()}-R-{sku}", "sku": sku,
                "created_date": day.isoformat(),
                "arrival_date": (day + timedelta(days=SUPPLY_LEAD_DAYS)).isoformat(),
                "ordered_boxes": quantity, "remaining_boxes": quantity,
            }
            supplies.append(supply)
            requests.append({
                "date": day.isoformat(), "supply_id": supply["supply_id"],
                "sku": sku, "zone": item["zone"], "stock_boxes": physical,
                "pending_boxes": demand, "incoming_boxes": incoming,
                "stock_position": position, "ordered_boxes": quantity,
                "arrival_date": supply["arrival_date"],
                "position_after_order": position + quantity,
            })
    return requests


def validate_stock(stock):#проверка зон хранения, количества коробок на паллетах и лимитов ячеек по SKU и зонам
    for sku, item in stock.items():
        if item["zone"] not in ZONE_CAPACITY:
            raise ValueError(f"Неизвестная зона для {sku}")
        if len(item["pallets"]) > SKU_CELL_CAPACITY:
            raise ValueError(f"Превышен лимит ячеек {sku}")
        if any(type(boxes) is not int or not 0 < boxes <= PALLET_CAPACITY
               for boxes in item["pallets"]):
            raise ValueError(f"Некорректные паллеты {sku}")
    for zone, capacity in ZONE_CAPACITY.items():
        if capacity <= 0:
            raise ValueError("Вместимость зоны должна быть положительной")
        occupied = sum(len(item["pallets"]) for item in stock.values()
                       if item["zone"] == zone)
        if occupied > capacity:
            raise ValueError(f"Превышена вместимость зоны {zone}")
