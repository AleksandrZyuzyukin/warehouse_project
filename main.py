"""Приёмка, сборка, погрузка и отправка машин внутри последовательных смен."""

import argparse
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from config import SEED, SIMULATION_DAYS, ZONE_CAPACITY
from oms import generate_orders
from simulation import Warehouse
from wms import total_boxes


FIELDS = {
    'orders': ['date', 'order_id', 'created_at', 'deadline', 'sku', 'boxes'],
    'events': ['event_id', 'timestamp', 'event_type', 'sku', 'zone', 'boxes', 'order_id',
               'supply_id', 'truck_id', 'worker_id', 'equipment_id', 'finish_at'],
    'reservations': ['timestamp', 'order_id', 'sku', 'deadline', 'added_boxes', 'reserved_boxes', 'available_boxes'],
    'stock': ['date', 'sku', 'zone', 'stock_boxes', 'occupied_cells', 'reserved_boxes',
              'available_boxes', 'unpicked_boxes', 'waiting_boxes', 'incoming_boxes', 'stock_position'],
    'zones': ['date', 'zone', 'occupied_cells', 'capacity_cells', 'utilization', 'shipped_boxes'],
    'waiting': ['date', 'waiting_boxes', 'loaded_boxes', 'capacity_boxes', 'utilization'],
    'order_states': ['date', 'order_date', 'created_at', 'deadline', 'order_id', 'sku',
                     'ordered_boxes', 'unpicked_boxes', 'reserved_boxes', 'picking_boxes',
                     'waiting_boxes', 'loaded_boxes', 'loading_boxes', 'shipped_boxes',
                     'cancelled_boxes', 'status', 'overdue_boxes'],
    'supplies': ['date', 'supply_id', 'sku', 'created_date', 'arrival_date', 'ordered_boxes',
                 'remaining_boxes', 'receiving_boxes', 'arrived_at', 'status'],
    'trucks': ['date', 'truck_id', 'arrival_at', 'departure_at', 'capacity_boxes', 'loaded_boxes', 'status'],
    'resources': ['date', 'resource_type', 'resource_id', 'busy_minutes', 'shift_minutes', 'utilization'],
    'replenishment': ['date', 'supply_id', 'sku', 'created_date', 'arrival_date', 'ordered_boxes',
                      'remaining_boxes', 'receiving_boxes', 'stock_boxes', 'pending_boxes',
                      'incoming_boxes', 'stock_position', 'position_after_order'],
    'summary': ['date', 'seed', 'orders', 'requested_boxes', 'accepted_boxes', 'picked_boxes',
                'loaded_boxes', 'shipped_boxes', 'stock_boxes', 'waiting_boxes', 'reserved_boxes',
                'unpicked_boxes', 'unfinished_boxes', 'unfinished_orders', 'overdue_boxes',
                'late_shipped_boxes', 'incoming_boxes', 'ordered_boxes'],
}


def write_csv(path, rows, fields):#запись таблицы с заголовками даже при отсутствии строк
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def save_day(tables, warehouse, day, orders, events, seed):#снимки состояния, ресурсы и показатели на закрытие дня
    date_text = day.isoformat()
    for order in orders:
        tables['orders'].extend({key: order[key] for key in ('date', 'order_id', 'created_at', 'deadline')} | line
                                for line in order['lines'])
    rows = list(warehouse.lines())
    for order, line in rows:
        unfinished = line['unpicked_boxes'] + line['waiting_boxes']
        tables['order_states'].append(dict(date=date_text, order_date=order['date'],
            created_at=order['created_at'], deadline=order['deadline'], order_id=order['order_id'],
            **line, status=warehouse.line_status(line),
            overdue_boxes=unfinished if order['deadline'] <= date_text else 0))
    for sku, item in warehouse.stock.items():
        physical = total_boxes(item['pallets'])
        reserved = warehouse.reserved_boxes(sku)
        unpicked = sum(line['unpicked_boxes'] for _, line in rows if line['sku'] == sku)
        waiting = sum(line['waiting_boxes'] for _, line in rows if line['sku'] == sku)
        incoming = sum(s['remaining_boxes'] for s in warehouse.supplies if s['sku'] == sku)
        tables['stock'].append(dict(date=date_text, sku=sku, zone=item['zone'],
            stock_boxes=physical, occupied_cells=len(item['pallets']), reserved_boxes=reserved,
            available_boxes=physical-reserved, unpicked_boxes=unpicked, waiting_boxes=waiting,
            incoming_boxes=incoming, stock_position=physical-unpicked+incoming))
    for zone, capacity in ZONE_CAPACITY.items():
        occupied = sum(len(item['pallets']) for item in warehouse.stock.values() if item['zone'] == zone)
        tables['zones'].append(dict(date=date_text, zone=zone, occupied_cells=occupied,
            capacity_cells=capacity, utilization=occupied/capacity,
            shipped_boxes=sum(e['boxes'] for e in events if e['event_type'] == 'shipped' and e['zone'] == zone)))
    waiting = warehouse.waiting_boxes()
    tables['waiting'].append(dict(date=date_text, waiting_boxes=waiting,
        loaded_boxes=sum(line['loaded_boxes'] for _, line in rows),
        capacity_boxes=warehouse.settings['WAITING_CAPACITY'], utilization=waiting/warehouse.settings['WAITING_CAPACITY']))
    for supply in warehouse.supplies:
        status = 'accepted' if supply['remaining_boxes'] == 0 else 'awaiting_receipt' if supply.get('arrived_at') else 'in_transit'
        tables['supplies'].append(dict(date=date_text, **supply, status=status,
            **({} if 'arrived_at' in supply else {'arrived_at': ''})))
    for truck in warehouse.trucks:
        if truck['arrival_at'][:10] == date_text:
            tables['trucks'].append(dict(date=date_text,
                **{key: truck[key] for key in FIELDS['trucks'] if key != 'date'}))
    shift_minutes = warehouse.settings['SHIFT_END_MINUTE'] - warehouse.settings['SHIFT_START_MINUTE']
    for kind, count, prefix, field in [('employee', warehouse.settings['EMPLOYEES'], 'W', 'worker_id'),
                                     ('equipment', warehouse.settings['EQUIPMENT'], 'T', 'equipment_id')]:
        for index in range(count):
            identifier = prefix + str(index+1)
            busy = sum(int((datetime.fromisoformat(e['finish_at']) -
                            datetime.fromisoformat(e['timestamp'])).total_seconds()/60)
                       for e in events if e['finish_at'] and e[field] == identifier)
            tables['resources'].append(dict(date=date_text, resource_type=kind, resource_id=identifier,
                busy_minutes=busy, shift_minutes=shift_minutes, utilization=busy/shift_minutes))
    event_total = lambda kind: sum(e['boxes'] for e in events if e['event_type'] == kind)
    unfinished_orders = {order['order_id'] for order, line in rows if line['unpicked_boxes'] + line['waiting_boxes']}
    tables['summary'].append(dict(date=date_text, seed=seed, orders=len(orders),
        requested_boxes=sum(line['boxes'] for order in orders for line in order['lines']),
        accepted_boxes=event_total('receipt_completed'), picked_boxes=event_total('pick_completed'),
        loaded_boxes=event_total('load_completed'), shipped_boxes=event_total('shipped'),
        stock_boxes=sum(total_boxes(item['pallets']) for item in warehouse.stock.values()),
        waiting_boxes=waiting, reserved_boxes=sum(line['reserved_boxes'] for _, line in rows),
        unpicked_boxes=sum(line['unpicked_boxes'] for _, line in rows),
        unfinished_boxes=sum(line['unpicked_boxes'] + line['waiting_boxes'] for _, line in rows),
        unfinished_orders=len(unfinished_orders),
        overdue_boxes=sum(line['unpicked_boxes'] + line['waiting_boxes'] for order, line in rows if order['deadline'] <= date_text),
        late_shipped_boxes=sum(e['boxes'] for e in events if e['event_type'] == 'shipped'
                               and warehouse.orders[e['order_id']]['deadline'] < date_text),
        incoming_boxes=sum(s['remaining_boxes'] for s in warehouse.supplies),
        ordered_boxes=event_total('supply_ordered')))


def run(day, output, seed=SEED, days=SIMULATION_DAYS, stock=None, settings=None, order_generator=generate_orders):#моделирование нескольких смен и сохранение таблиц
    if type(days) is not int or days <= 0:
        raise ValueError('Число дней должно быть положительным целым')
    warehouse = Warehouse(stock, settings)
    tables = {name: [] for name in FIELDS}
    for offset in range(days):
        current = day + timedelta(days=offset)
        orders = order_generator(current, tuple(warehouse.stock), seed)
        start = len(warehouse.events)
        warehouse.run_day(current, orders)
        events = warehouse.events[start:]
        save_day(tables, warehouse, current, orders, events, seed)
    tables['events'] = warehouse.events
    tables['reservations'] = warehouse.reservations
    tables['replenishment'] = warehouse.replenishment
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        write_csv(output / (name + '.csv'), rows, FIELDS[name])
    (output/'state.json').write_text(json.dumps(warehouse.state(current), ensure_ascii=False, indent=2), encoding='utf-8')
    return tables['summary']


def main():#параметры запуска, моделирование и вывод итогов
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', type=date.fromisoformat, default=date(2026, 9, 28))
    parser.add_argument('--days', type=int, default=SIMULATION_DAYS)
    parser.add_argument('--seed', type=int, default=SEED)
    parser.add_argument('--output', type=Path, default=Path('output'))
    args = parser.parse_args()
    if args.days <= 0:
        parser.error('--days должно быть положительным')
    summaries = run(args.date, args.output, args.seed, args.days)
    last = summaries[-1]
    print(f"Дней: {len(summaries)}; отправлено: {sum(row['shipped_boxes'] for row in summaries)} коробок")
    print(f"Конец {last['date']}: хранение {last['stock_boxes']}; ожидание {last['waiting_boxes']}; незавершено {last['unfinished_boxes']}")
    print(f'Файлы: {args.output.resolve()}')


if __name__ == '__main__':
    main()
