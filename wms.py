from datetime import timedelta

from config import (
    PALLET_CAPACITY, REORDER_POINT, SKU_CELL_CAPACITY,
    SUPPLY_LEAD_DAYS, TARGET_STOCK_POSITION, ZONE_CAPACITY,
)


def total_boxes(pallets):#общее количество коробок на паллетах
    return sum(pallets)


def occupied_cells(pallets):#количество занятых ячеек
    return len(pallets)


def check_quantity(quantity):#проверка целого неотрицательного количества
    if type(quantity) is not int or quantity < 0:
        raise ValueError("Количество должно быть целым и неотрицательным")


def ship_boxes(pallets, requested):#списание товара, сначала с неполных паллет
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


def receive_boxes(stock, sku, requested):#приёмка SKU с учётом лимитов ячеек товара и зоны
    check_quantity(requested)
    item = stock[sku]
    pallets = item["pallets"]
    remaining = requested

    # Заполнение существующих паллет не требует новых ячеек.
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


def receive_deliveries(stock, supplies, day):#приёмка прибывших поставок и перенос непринятой части
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


def priority_key(order):#приоритет по сроку отправки, времени поступления и идентификатору
    return (order.get("deadline", order["date"]),
            order.get("created_at", order["date"] + "T00:00:00"), order["order_id"])


def reserved_boxes(orders, sku):#количество коробок SKU, закреплённых за строками заказов
    return sum(line.get("reserved_boxes", 0) for order in orders
               for line in order["lines"] if line["sku"] == sku)


def validate_reservations(stock, orders):#проверка резервов по строкам и соответствия физическому остатку
    for order in orders:
        for line in order["lines"]:
            check_quantity(line["boxes"])
            reserved = line.get("reserved_boxes", 0)
            check_quantity(reserved)
            if line["sku"] not in stock or reserved > line["boxes"]:
                raise ValueError("Некорректный резерв строки заказа")
    for sku in stock:
        if reserved_boxes(orders, sku) > total_boxes(stock[sku]["pallets"]):
            raise ValueError(f"Резерв превышает физический остаток {sku}")


def reserve_orders(stock, orders, day):#распределение доступного товара по приоритету без изменения паллет
    validate_reservations(stock, orders)
    available = {sku: total_boxes(item["pallets"]) - reserved_boxes(orders, sku)
                 for sku, item in stock.items()}
    reservations = []
    for order in sorted(orders, key=priority_key):
        if order["date"] > day.isoformat():
            raise ValueError("Нельзя резервировать ещё не поступивший заказ")
        for line in order["lines"]:
            sku = line["sku"]
            before = line.get("reserved_boxes", 0)
            added = min(line["boxes"] - before, available[sku])
            line["reserved_boxes"] = before + added
            available[sku] -= added
            reservations.append({
                "date": day.isoformat(), "order_id": order["order_id"],
                "sku": sku, "deadline": order.get("deadline", order["date"]),
                "created_at": order.get("created_at", order["date"] + "T00:00:00"),
                "requested_boxes": line["boxes"], "reserved_before_boxes": before,
                "new_reserved_boxes": added, "reserved_boxes": line["reserved_boxes"],
                "unreserved_boxes": line["boxes"] - line["reserved_boxes"],
                "available_after_boxes": available[sku],
            })
    validate_reservations(stock, orders)
    return reservations


def process_orders(stock, orders, day):#отгрузка только из резервов по приоритету и перенос невыполненных частей
    validate_reservations(stock, orders)
    operations, pending = [], []
    for order in sorted(orders, key=priority_key):
        pending_lines = []
        for line in order["lines"]:
            sku = line["sku"]
            reserved = line.get("reserved_boxes", 0)
            pallets, shipped, shortage = ship_boxes(stock[sku]["pallets"], reserved)
            if shortage:
                raise ValueError("Недостаточно товара для исполнения резерва")
            stock[sku]["pallets"] = pallets
            line["reserved_boxes"] = reserved - shipped
            unfulfilled = line["boxes"] - shipped
            deadline = order.get("deadline", order["date"])
            late = day.isoformat() > deadline
            operations.append({
                "date": day.isoformat(), "order_date": order["date"],
                "created_at": order.get("created_at", order["date"] + "T00:00:00"),
                "deadline": deadline, "order_id": order["order_id"], "sku": sku,
                "zone": stock[sku]["zone"], "requested_boxes": line["boxes"],
                "reserved_boxes": reserved, "shipped_boxes": shipped,
                "unfulfilled_boxes": unfulfilled, "late_shipped_boxes": shipped if late else 0,
                "overdue_boxes": unfulfilled if day.isoformat() >= deadline else 0,
            })
            if unfulfilled:
                pending_lines.append({"sku": sku, "boxes": unfulfilled,
                                      "reserved_boxes": line["reserved_boxes"]})
        if pending_lines:
            pending.append({**order, "lines": pending_lines})
    validate_reservations(stock, pending)
    return operations, pending


def plan_replenishment(stock, pending, supplies, day):#пополнение позиции запаса с учётом спроса и поставок
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


def validate_stock(stock):#проверка паллет, зон и лимитов ячеек
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
