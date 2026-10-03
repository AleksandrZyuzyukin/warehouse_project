#События склада внутри смены. Каждая операция обрабатывает одну коробку.

from copy import deepcopy
from datetime import date, datetime, time, timedelta

import config
from wms import total_boxes, receive_boxes, ship_boxes, validate_stock


class Warehouse:
    def __init__(self, stock=None, settings=None):#начальное состояние склада и параметры моделирования
        names = ('SHIFT_START_MINUTE', 'SHIFT_END_MINUTE', 'EMPLOYEES', 'EQUIPMENT',
                 'RECEIPT_MINUTES', 'PICK_MINUTES', 'LOAD_MINUTES', 'WAITING_CAPACITY',
                 'TRUCK_CAPACITY', 'TRUCK_SCHEDULE', 'REORDER_POINT',
                 'TARGET_STOCK_POSITION', 'SUPPLY_LEAD_DAYS')
        self.settings = {name: getattr(config, name) for name in names}
        self.settings.update(settings or {})
        self.stock = deepcopy(config.INITIAL_STOCK if stock is None else stock)
        validate_stock(self.stock)
        self.initial = {sku: total_boxes(item['pallets']) for sku, item in self.stock.items()}
        self.accepted = {sku: 0 for sku in self.stock}
        self.sent = {sku: 0 for sku in self.stock}
        self.orders, self.supplies, self.trucks = {}, [], []
        self.active_order_ids = set()
        self.tasks, self.completed_tasks = [], set()
        self.events, self.reservations, self.replenishment = [], [], []
        self.sequence = 0
        for name in ('EMPLOYEES', 'EQUIPMENT', 'RECEIPT_MINUTES', 'PICK_MINUTES',
                     'LOAD_MINUTES', 'WAITING_CAPACITY', 'TRUCK_CAPACITY'):
            if type(self.settings[name]) is not int or self.settings[name] <= 0:
                raise ValueError(f'Некорректный параметр {name}')
        if not 0 <= self.settings['SHIFT_START_MINUTE'] < self.settings['SHIFT_END_MINUTE'] < 1440:
            raise ValueError('Некорректное время смены')
        for arrival, departure in self.settings['TRUCK_SCHEDULE']:
            if not self.settings['SHIFT_START_MINUTE'] <= arrival < departure <= self.settings['SHIFT_END_MINUTE']:
                raise ValueError('Расписание машины должно быть внутри смены')

    def timestamp(self, day, minute):#перевод номера минуты в дату и время
        return datetime.combine(day, time()) + timedelta(minutes=minute)

    def log(self, moment, kind, boxes=0, sku='', order_id='', supply_id='', truck_id='',
            worker='', equipment='', finish_at=''):#запись фактического события с уникальным идентификатором
        self.sequence += 1
        row = dict(event_id=f'E{self.sequence:08d}', timestamp=moment.isoformat(),
                   event_type=kind, sku=sku, zone=self.stock[sku]['zone'] if sku else '',
                   boxes=boxes, order_id=order_id, supply_id=supply_id, truck_id=truck_id,
                   worker_id=worker, equipment_id=equipment, finish_at=finish_at)
        self.events.append(row)
        return row['event_id']

    def lines(self, active_only=False):#перебор строк заказов, при необходимости только незавершённых
        orders = (self.orders[key] for key in sorted(self.active_order_ids)) if active_only else self.orders.values()
        for order in orders:
            for line in order['lines']:
                yield order, line

    def priority(self, order):#срок отправки, время поступления, идентификатор
        return self.timestamp(date.fromisoformat(order['deadline']), self.settings['SHIFT_END_MINUTE']).isoformat(), order['created_at'], order['order_id']

    def waiting_boxes(self):#коробки в зоне ожидания, включая загруженные до отправления
        return sum(line['waiting_boxes'] for _, line in self.lines(active_only=True))

    def reserved_boxes(self, sku):#резерв SKU на хранении, включая выполняемую сборку
        return sum(line['reserved_boxes'] for _, line in self.lines(active_only=True) if line['sku'] == sku)

    def register_order(self, source, moment):#регистрация заказа без повторного добавления того же идентификатора
        identifier = source['order_id']
        if identifier in self.orders:
            if self.orders[identifier]['source'] != source:
                raise ValueError('Повторный идентификатор с другим содержимым заказа')
            return
        created = datetime.fromisoformat(source['created_at'])
        if created > moment:
            raise ValueError('Заказ ещё не поступил')
        if source['deadline'] < created.date().isoformat():
            raise ValueError('Срок отправки раньше даты заказа')
        if len({line['sku'] for line in source['lines']}) != len(source['lines']):
            raise ValueError('SKU строк заказа должны различаться')
        order = {key: source[key] for key in ('order_id', 'date', 'created_at', 'deadline')}
        order['source'] = deepcopy(source)
        order['lines'] = []
        for row in source['lines']:
            if row['sku'] not in self.stock or type(row['boxes']) is not int or row['boxes'] <= 0:
                raise ValueError('Некорректная строка заказа')
            order['lines'].append(dict(sku=row['sku'], ordered_boxes=row['boxes'],
                                       unpicked_boxes=row['boxes'], reserved_boxes=0,
                                       picking_boxes=0, waiting_boxes=0, loaded_boxes=0,
                                       loading_boxes=0, shipped_boxes=0, cancelled_boxes=0))
        self.orders[identifier] = order
        self.active_order_ids.add(identifier)
        self.log(moment, 'order_received', order_id=identifier)

    def reserve(self, moment):#закрепление свободного товара за заказами без отъёма существующих резервов
        available = {sku: total_boxes(item['pallets']) - self.reserved_boxes(sku)
                     for sku, item in self.stock.items()}
        for order in sorted((self.orders[key] for key in self.active_order_ids), key=self.priority):
            for line in order['lines']:
                sku = line['sku']
                added = min(line['unpicked_boxes'] - line['reserved_boxes'], available[sku])
                if added:
                    line['reserved_boxes'] += added
                    available[sku] -= added
                    self.log(moment, 'reserved', added, sku, order['order_id'])
                    self.reservations.append(dict(timestamp=moment.isoformat(),
                        order_id=order['order_id'], sku=sku, deadline=order['deadline'],
                        added_boxes=added, reserved_boxes=line['reserved_boxes'],
                        available_boxes=available[sku]))

    def can_receive(self, sku):#проверка места с учётом уже начатых операций приёмки
        projected = deepcopy(self.stock)
        for task in self.tasks:
            if task['kind'] == 'receipt':
                accepted, _ = receive_boxes(projected, task['sku'], 1)
                if accepted != 1:
                    raise ValueError('Нарушен план размещения начатой приёмки')
        return receive_boxes(projected, sku, 1)[0] == 1

    def candidates(self, day, minute):#доступные операции с приоритетом по ближайшему сроку
        moment = self.timestamp(day, minute)
        end = self.settings['SHIFT_END_MINUTE']
        result = []
        for supply in self.supplies:
            if supply['arrival_date'] <= day.isoformat() and supply['remaining_boxes'] > supply['receiving_boxes']:
                if minute + self.settings['RECEIPT_MINUTES'] <= end and self.can_receive(supply['sku']):
                    result.append(dict(kind='receipt', sku=supply['sku'], supply=supply,
                        key=(supply['arrival_date'] + 'T09:00:00', supply['created_date'] + 'T17:00:00',
                             '0', supply['supply_id'])))
        booked = self.waiting_boxes() + sum(line['picking_boxes'] for _, line in self.lines(active_only=True))
        for identifier in sorted(self.active_order_ids):
            order = self.orders[identifier]
            for line in order['lines']:
                if line['reserved_boxes'] > line['picking_boxes'] and booked < self.settings['WAITING_CAPACITY']:
                    if minute + self.settings['PICK_MINUTES'] <= end:
                        result.append(dict(kind='pick', sku=line['sku'], order=order, line=line,
                            key=(*self.priority(order)[:2], '1', order['order_id'], line['sku'])))
                ready = line['waiting_boxes'] - line['loaded_boxes'] - line['loading_boxes']
                if ready <= 0:
                    continue
                for truck in self.trucks:
                    if truck['status'] != 'arrived':
                        continue
                    if truck['loaded_boxes'] + truck['loading_boxes'] >= truck['capacity_boxes']:
                        continue
                    if moment + timedelta(minutes=self.settings['LOAD_MINUTES']) > datetime.fromisoformat(truck['departure_at']):
                        continue
                    result.append(dict(kind='load', sku=line['sku'], order=order, line=line, truck=truck,
                        key=(min(self.priority(order)[0], truck['departure_at']), order['created_at'],
                             '2', order['order_id'], line['sku'], truck['truck_id'])))
        return sorted(result, key=lambda task: task['key'])

    def schedule(self, day, minute):#назначение свободных сотрудников и техники на операции
        while True:
            workers = {task['worker'] for task in self.tasks}
            worker = next((f'W{i+1}' for i in range(self.settings['EMPLOYEES']) if f'W{i+1}' not in workers), None)
            if worker is None:
                return
            devices = {task['equipment'] for task in self.tasks if task['equipment']}
            equipment = next((f'T{i+1}' for i in range(self.settings['EQUIPMENT']) if f'T{i+1}' not in devices), None)
            chosen = next((task for task in self.candidates(day, minute)
                           if task['kind'] == 'load' or equipment is not None), None)
            if chosen is None:
                return
            kind = chosen['kind']
            duration = self.settings[{'receipt': 'RECEIPT_MINUTES', 'pick': 'PICK_MINUTES', 'load': 'LOAD_MINUTES'}[kind]]
            chosen.update(worker=worker, equipment='' if kind == 'load' else equipment,
                          end_minute=minute + duration)
            if kind == 'receipt':
                chosen['supply']['receiving_boxes'] += 1
            elif kind == 'pick':
                chosen['line']['picking_boxes'] += 1
            else:
                chosen['line']['loading_boxes'] += 1
                chosen['truck']['loading_boxes'] += 1
            chosen['task_id'] = self.log(self.timestamp(day, minute), kind + '_started', 1, chosen['sku'],
                chosen.get('order', {}).get('order_id', ''), chosen.get('supply', {}).get('supply_id', ''),
                chosen.get('truck', {}).get('truck_id', ''), worker, chosen['equipment'],
                self.timestamp(day, minute + duration).isoformat())
            self.tasks.append(chosen)

    def complete_task(self, task, moment):#завершение операции один раз и изменение физических количеств
        if task['task_id'] in self.completed_tasks:
            return
        kind, sku = task['kind'], task['sku']
        if kind == 'receipt':
            accepted, _ = receive_boxes(self.stock, sku, 1)
            if accepted != 1:
                raise ValueError('Для начатой приёмки нет места')
            task['supply']['remaining_boxes'] -= 1
            task['supply']['receiving_boxes'] -= 1
            self.accepted[sku] += 1
        elif kind == 'pick':
            line = task['line']
            pallets, shipped, _ = ship_boxes(self.stock[sku]['pallets'], 1)
            if shipped != 1:
                raise ValueError('Нет зарезервированного товара')
            self.stock[sku]['pallets'] = pallets
            line['unpicked_boxes'] -= 1
            line['reserved_boxes'] -= 1
            line['picking_boxes'] -= 1
            line['waiting_boxes'] += 1
        else:
            line, truck = task['line'], task['truck']
            line['loading_boxes'] -= 1
            line['loaded_boxes'] += 1
            truck['loading_boxes'] -= 1
            truck['loaded_boxes'] += 1
            truck['manifest'].append((task['order']['order_id'], sku))
        self.completed_tasks.add(task['task_id'])
        self.log(moment, kind + '_completed', 1, sku,
                 task.get('order', {}).get('order_id', ''), task.get('supply', {}).get('supply_id', ''),
                 task.get('truck', {}).get('truck_id', ''), task['worker'], task['equipment'])

    def depart(self, truck, moment):#подтверждение отправки и списание загруженных коробок из зоны ожидания
        if truck['status'] == 'departed':
            return
        if truck['loading_boxes']:
            raise ValueError('Погрузка должна завершиться до отправления')
        for order_id, sku in truck['manifest']:
            line = next(line for line in self.orders[order_id]['lines'] if line['sku'] == sku)
            line['loaded_boxes'] -= 1
            line['waiting_boxes'] -= 1
            line['shipped_boxes'] += 1
            self.sent[sku] += 1
            self.log(moment, 'shipped', 1, sku, order_id, truck_id=truck['truck_id'])
        for order_id in {identifier for identifier, _ in truck['manifest']}:
            if all(line['shipped_boxes'] == line['ordered_boxes'] for line in self.orders[order_id]['lines']):
                self.active_order_ids.discard(order_id)
        truck['status'] = 'departed'
        self.log(moment, 'truck_departed', truck['loaded_boxes'], truck_id=truck['truck_id'])

    def plan_replenishment(self, day):#заявка до целевой позиции с учётом ещё не собранного спроса и поставок
        for sku, item in self.stock.items():
            demand = sum(line['unpicked_boxes'] for _, line in self.lines(active_only=True) if line['sku'] == sku)
            incoming = sum(s['remaining_boxes'] for s in self.supplies if s['sku'] == sku)
            physical = total_boxes(item['pallets'])
            position = physical - demand + incoming
            if position <= self.settings['REORDER_POINT']:
                quantity = self.settings['TARGET_STOCK_POSITION'] - position
                supply = dict(supply_id=f'{day.isoformat()}-R-{sku}', sku=sku,
                    created_date=day.isoformat(),
                    arrival_date=(day + timedelta(days=self.settings['SUPPLY_LEAD_DAYS'])).isoformat(),
                    ordered_boxes=quantity, remaining_boxes=quantity, receiving_boxes=0)
                self.supplies.append(supply)
                self.replenishment.append(dict(date=day.isoformat(), **supply,
                    stock_boxes=physical, pending_boxes=demand, incoming_boxes=incoming,
                    stock_position=position, position_after_order=position + quantity))
                self.log(self.timestamp(day, self.settings['SHIFT_END_MINUTE']), 'supply_ordered',
                         quantity, sku, supply_id=supply['supply_id'])

    def validate(self, full=False):#баланс SKU, строки заказов, резервы, вместимости и занятость ресурсов
        validate_stock(self.stock)
        for sku, item in self.stock.items():
            physical = total_boxes(item['pallets'])
            waiting = sum(line['waiting_boxes'] for _, line in self.lines(active_only=True) if line['sku'] == sku)
            if physical + waiting != self.initial[sku] + self.accepted[sku] - self.sent[sku]:
                raise ValueError(f'Нарушен физический баланс {sku}')
            if self.reserved_boxes(sku) > physical:
                raise ValueError(f'Резерв превышает остаток {sku}')
        for _, line in self.lines(active_only=not full):
            for key, value in line.items():
                if key != 'sku' and (type(value) is not int or value < 0):
                    raise ValueError('Некорректное количество строки')
            if line['unpicked_boxes'] + line['waiting_boxes'] + line['shipped_boxes'] + line['cancelled_boxes'] != line['ordered_boxes']:
                raise ValueError('Нарушен баланс строки заказа')
            if not line['picking_boxes'] <= line['reserved_boxes'] <= line['unpicked_boxes']:
                raise ValueError('Некорректный резерв')
            if line['loaded_boxes'] + line['loading_boxes'] > line['waiting_boxes']:
                raise ValueError('Нельзя загрузить неподготовленные коробки')
        if self.waiting_boxes() + sum(line['picking_boxes'] for _, line in self.lines(active_only=True)) > self.settings['WAITING_CAPACITY']:
            raise ValueError('Превышена вместимость зоны ожидания')
        if len({task['worker'] for task in self.tasks}) != len(self.tasks):
            raise ValueError('Сотрудник назначен дважды')
        equipment = [task['equipment'] for task in self.tasks if task['equipment']]
        if len(set(equipment)) != len(equipment):
            raise ValueError('Техника назначена дважды')
        for truck in self.trucks:
            if truck['loaded_boxes'] + truck['loading_boxes'] > truck['capacity_boxes']:
                raise ValueError('Превышена вместимость машины')
        for supply in self.supplies:
            if not 0 <= supply['receiving_boxes'] <= supply['remaining_boxes']:
                raise ValueError('Некорректная приёмка поставки')

    def run_day(self, day, orders):#последовательная обработка событий дня без доступа к будущим заказам
        if self.tasks:
            raise ValueError('Операции прошлого дня не завершены')
        end = self.settings['SHIFT_END_MINUTE']
        arrival_orders = sorted(orders, key=lambda row: (row['created_at'], row['order_id']))
        for source in arrival_orders:
            if source['date'] != day.isoformat() or datetime.fromisoformat(source['created_at']).date() != day:
                raise ValueError('Дата заказа не соответствует дню')
            if datetime.fromisoformat(source['created_at']) > self.timestamp(day, end):
                raise ValueError('Время заказа позже закрытия дня')
        today_trucks = []
        for index, (arrival, departure) in enumerate(self.settings['TRUCK_SCHEDULE'], 1):
            truck = dict(truck_id=f'{day.isoformat()}-T{index}',
                arrival_at=self.timestamp(day, arrival).isoformat(),
                departure_at=self.timestamp(day, departure).isoformat(),
                capacity_boxes=self.settings['TRUCK_CAPACITY'], status='planned',
                loaded_boxes=0, loading_boxes=0, manifest=[])
            self.trucks.append(truck)
            today_trucks.append(truck)
        next_order = 0
        for minute in range(end + 1):
            moment = self.timestamp(day, minute)
            due = [task for task in self.tasks if task['end_minute'] == minute]
            for task in due:
                self.complete_task(task, moment)
            self.tasks[:] = [task for task in self.tasks if task not in due]
            for truck in today_trucks:
                if truck['arrival_at'] == moment.isoformat():
                    truck['status'] = 'arrived'
                    self.log(moment, 'truck_arrived', truck_id=truck['truck_id'])
                if truck['departure_at'] == moment.isoformat():
                    self.depart(truck, moment)
            if minute == self.settings['SHIFT_START_MINUTE']:
                for supply in self.supplies:
                    if supply['arrival_date'] <= day.isoformat() and not supply.get('arrived_at'):
                        supply['arrived_at'] = moment.isoformat()
                        self.log(moment, 'supply_arrived', supply['remaining_boxes'], supply['sku'],
                                 supply_id=supply['supply_id'])
            while next_order < len(arrival_orders) and datetime.fromisoformat(arrival_orders[next_order]['created_at']) <= moment:
                self.register_order(arrival_orders[next_order], moment)
                next_order += 1
            self.reserve(moment)
            if self.settings['SHIFT_START_MINUTE'] <= minute < end:
                self.schedule(day, minute)
            self.validate()
        if self.tasks:
            raise ValueError('Операция вышла за пределы смены')
        self.plan_replenishment(day)
        self.validate(full=True)
        self.log(self.timestamp(day, end), 'shift_closed')

    def line_status(self, line):#статус строки по ещё не собранным, подготовленным и отправленным коробкам
        if line['shipped_boxes'] == line['ordered_boxes']:
            return 'completed'
        if line['shipped_boxes']:
            return 'partially_shipped'
        if line['unpicked_boxes'] == 0:
            return 'awaiting_shipment'
        if line['waiting_boxes']:
            return 'partially_picked'
        return 'awaiting_pick'

    def state(self, day):#конечное состояние для проверки и дальнейшего расширения модели
        return dict(date=day.isoformat(), stock=self.stock, orders=list(self.orders.values()),
                    supplies=self.supplies, trucks=self.trucks,
                    initial_boxes=self.initial, accepted_boxes=self.accepted, shipped_boxes=self.sent)
