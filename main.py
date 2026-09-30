"""Один независимый день: заказы → склад → CSV-файлы."""

import argparse
import csv
from copy import deepcopy
from datetime import date
from pathlib import Path

from config import INITIAL_STOCK, PALLET_CAPACITY, SEED, ZONE_CAPACITY
from oms import generate_orders
from wms import occupied_cells, process_orders, total_boxes


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(day, output, seed=SEED):
    stock = deepcopy(INITIAL_STOCK)
    initial_boxes = sum(total_boxes(item["pallets"]) for item in stock.values())# кол-во товаров каждого типа
    orders = generate_orders(day, tuple(stock), seed)#генерация заказов
    operations = process_orders(stock, orders)

    stock_rows = []#таблица остатков
    for sku, item in stock.items():
        assert all(0 < boxes <= PALLET_CAPACITY for boxes in item["pallets"])
        stock_rows.append({
            "date": day.isoformat(), "sku": sku, "zone": item["zone"],
            "stock_boxes": total_boxes(item["pallets"]),
            "occupied_cells": occupied_cells(item["pallets"]),
        })

    zone_rows = []#таблица зон склада
    for zone, capacity in ZONE_CAPACITY.items():
        occupied = sum(row["occupied_cells"] for row in stock_rows if row["zone"] == zone)
        assert occupied <= capacity
        zone_rows.append({
            "date": day.isoformat(), "zone": zone,
            "occupied_cells": occupied, "capacity_cells": capacity,
            "utilization": occupied / capacity,
        })

    shipped = sum(row["shipped_boxes"] for row in operations)
    remaining = sum(row["stock_boxes"] for row in stock_rows)
    assert initial_boxes == shipped + remaining, "Нарушен баланс коробок"
    summary = {
        "date": day.isoformat(), "seed": seed, "orders": len(orders),
        "requested_boxes": sum(row["requested_boxes"] for row in operations),
        "shipped_boxes": shipped,
        "unfulfilled_boxes": sum(row["unfulfilled_boxes"] for row in operations),
        "stock_boxes": remaining,
    }

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    order_rows = [{"date": order["date"], "order_id": order["order_id"], **line}
                  for order in orders for line in order["lines"]]# таблица заказов
    write_csv(output / "orders.csv", order_rows)
    write_csv(output / "operations.csv", operations)
    write_csv(output / "stock.csv", stock_rows)
    write_csv(output / "zones.csv", zone_rows)
    write_csv(output / "summary.csv", [summary])
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=date(2026, 9, 28))
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    summary = run(args.date, args.output, args.seed)
    print(f"Заказов: {summary['orders']}; отгружено: {summary['shipped_boxes']} коробок")
    print(f"Остаток: {summary['stock_boxes']} коробок; файлы: {args.output.resolve()}")


if __name__ == "__main__":
    main()
