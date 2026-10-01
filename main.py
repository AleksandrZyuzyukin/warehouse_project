"""Последовательные дни: приёмка → заказы → пополнение → CSV."""

import argparse
import csv
import json
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

from config import INITIAL_STOCK, SEED, SIMULATION_DAYS, ZONE_CAPACITY
from oms import generate_orders
from wms import (occupied_cells, plan_replenishment, process_orders,
                 receive_deliveries, total_boxes, validate_stock)


FIELDS = {
    "orders": ["date", "order_id", "sku", "boxes"],
    "operations": ["date", "order_date", "order_id", "sku", "zone",
                   "requested_boxes", "shipped_boxes", "unfulfilled_boxes"],
    "receipts": ["date", "supply_id", "sku", "zone", "offered_boxes",
                 "accepted_boxes", "unaccepted_boxes"],
    "replenishment": ["date", "supply_id", "sku", "zone", "stock_boxes",
                      "pending_boxes", "incoming_boxes", "stock_position",
                      "ordered_boxes", "arrival_date", "position_after_order"],
    "stock": ["date", "sku", "zone", "stock_boxes", "occupied_cells",
              "pending_boxes", "incoming_boxes", "stock_position"],
    "zones": ["date", "zone", "occupied_cells", "capacity_cells",
              "utilization", "shipped_boxes"],
    "pending_orders": ["date", "order_date", "order_id", "sku", "boxes"],
    "supplies": ["date", "supply_id", "sku", "created_date", "arrival_date",
                 "ordered_boxes", "remaining_boxes", "status"],
    "summary": ["date", "seed", "orders", "requested_boxes", "backlog_start_boxes",
                "accepted_boxes", "shipped_boxes", "unfulfilled_boxes",
                "pending_orders", "stock_boxes", "ordered_boxes", "incoming_boxes"],
}


def write_csv(path, rows, fieldnames):#запись таблицы в CSV-файл с заголовками, даже если строк нет
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def order_boxes(orders):#общее количество коробок во всех строках переданных заказов
    return sum(line["boxes"] for order in orders for line in order["lines"])


def run(day, output, seed=SEED, days=SIMULATION_DAYS):#моделирование последовательных дней с переносом остатков, незавершённых заказов и поставок. Сохранение таблиц и конечного состояния склада
    if type(days) is not int or days <= 0:
        raise ValueError("Число дней должно быть положительным целым")
    stock = deepcopy(INITIAL_STOCK)
    validate_stock(stock)
    pending, supplies = [], []
    tables = {name: [] for name in FIELDS}

    for offset in range(days):
        current = day + timedelta(days=offset)
        date_text = current.isoformat()
        opening = {sku: total_boxes(item["pallets"]) for sku, item in stock.items()}
        backlog_start = order_boxes(pending)

        receipts = receive_deliveries(stock, supplies, current)
        orders = generate_orders(current, tuple(stock), seed)
        operations, pending = process_orders(stock, pending + orders, current)
        requests = plan_replenishment(stock, pending, supplies, current)
        validate_stock(stock)

        # Проверяем баланс каждого SKU, а не только общий итог.
        for sku, item in stock.items():
            accepted = sum(row["accepted_boxes"] for row in receipts if row["sku"] == sku)
            shipped = sum(row["shipped_boxes"] for row in operations if row["sku"] == sku)
            if opening[sku] + accepted != total_boxes(item["pallets"]) + shipped:
                raise ValueError(f"Нарушен баланс коробок: {date_text}, {sku}")
        shipped = sum(row["shipped_boxes"] for row in operations)
        if backlog_start + order_boxes(orders) != shipped + order_boxes(pending):
            raise ValueError(f"Нарушен баланс заказов: {date_text}")

        tables["orders"].extend(
            {"date": order["date"], "order_id": order["order_id"], **line}
            for order in orders for line in order["lines"])
        tables["operations"].extend(operations)
        tables["receipts"].extend(receipts)
        tables["replenishment"].extend(requests)
        tables["pending_orders"].extend(
            {"date": date_text, "order_date": order["date"],
             "order_id": order["order_id"], **line}
            for order in pending for line in order["lines"])
        tables["supplies"].extend(
            {"date": date_text, **supply,
             "status": "awaiting_receipt" if supply["arrival_date"] <= date_text else "in_transit"}
            for supply in supplies)

        for sku, item in stock.items():
            demand = sum(line["boxes"] for order in pending for line in order["lines"]
                         if line["sku"] == sku)
            incoming = sum(supply["remaining_boxes"] for supply in supplies
                           if supply["sku"] == sku)
            physical = total_boxes(item["pallets"])
            tables["stock"].append({
                "date": date_text, "sku": sku, "zone": item["zone"],
                "stock_boxes": physical, "occupied_cells": occupied_cells(item["pallets"]),
                "pending_boxes": demand, "incoming_boxes": incoming,
                "stock_position": physical - demand + incoming,
            })
        for zone, capacity in ZONE_CAPACITY.items():
            occupied = sum(occupied_cells(item["pallets"]) for item in stock.values()
                           if item["zone"] == zone)
            tables["zones"].append({
                "date": date_text, "zone": zone, "occupied_cells": occupied,
                "capacity_cells": capacity, "utilization": occupied / capacity,
                "shipped_boxes": sum(row["shipped_boxes"] for row in operations
                                     if row["zone"] == zone),
            })
        tables["summary"].append({
            "date": date_text, "seed": seed, "orders": len(orders),
            "requested_boxes": order_boxes(orders), "backlog_start_boxes": backlog_start,
            "accepted_boxes": sum(row["accepted_boxes"] for row in receipts),
            "shipped_boxes": shipped, "unfulfilled_boxes": order_boxes(pending),
            "pending_orders": len(pending),
            "stock_boxes": sum(total_boxes(item["pallets"]) for item in stock.values()),
            "ordered_boxes": sum(row["ordered_boxes"] for row in requests),
            "incoming_boxes": sum(supply["remaining_boxes"] for supply in supplies),
        })

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        write_csv(output / f"{name}.csv", rows, FIELDS[name])
    state = {"date": date_text, "stock": stock, "pending_orders": pending, "supplies": supplies}
    (output / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return tables["summary"]


def main():#чтение параметров запуска, запуск моделирования и вывод итогов
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=date(2026, 9, 28))
    parser.add_argument("--days", type=int, default=SIMULATION_DAYS)
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    if args.days <= 0:
        parser.error("--days должно быть положительным")
    summaries = run(args.date, args.output, args.seed, args.days)
    last = summaries[-1]
    print(f"Дней: {len(summaries)}; отгружено: {sum(row['shipped_boxes'] for row in summaries)} коробок")
    print(f"Конец {last['date']}: остаток {last['stock_boxes']}; невыполнено {last['unfulfilled_boxes']} коробок")
    print(f"Файлы: {args.output.resolve()}")


if __name__ == "__main__":
    main()
