from config import PALLET_CAPACITY, SKU_CELL_CAPACITY, ZONE_CAPACITY


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
