#Воспроизводимые отклонения по seed, дате и идентификатору события.

import calendar
import hashlib
import random
from datetime import date, timedelta


class Conditions:
    def __init__(self, seed, settings):#параметры случайных условий, независимых от потока заказов OMS
        self.seed, self.settings = seed, settings

    def rng(self, category, identifier):#стабильное зерно для отдельного события без встроенного hash
        value = f'{self.seed}|{category}|{identifier}'.encode('utf-8')
        return random.Random(int.from_bytes(hashlib.sha256(value).digest(), 'big'))

    def no_show_day(self, day):#одна неявка на 90 дней без сближения случаев на границах периодов
        interval = self.settings['TRUCK_NO_SHOW_INTERVAL_DAYS']
        phase = self.rng('no_show_phase', 'warehouse').randrange(interval)
        return (day - date(2000, 1, 1)).days % interval == phase

    def truck(self, day, index, count):#неявка одного рейса либо задержка конкретной машины
        if not self.settings['VARIABILITY_ENABLED']:
            return {'no_show': False, 'delay_minutes': 0}
        missing_index = self.rng('no_show_truck', day.isoformat()).randrange(count) + 1
        no_show = self.no_show_day(day) and index == missing_index
        rng = self.rng('truck_delay', f'{day.isoformat()}-T{index}')
        delay = rng.randint(*self.settings['TRUCK_DELAY_MINUTES']) if rng.random() < self.settings['TRUCK_DELAY_PROBABILITY'] else 0
        return {'no_show': no_show, 'delay_minutes': 0 if no_show else delay}

    def supply(self, supply_id):#взаимоисключающие задержки отдельной поставки SKU: минуты или дни
        if not self.settings['VARIABILITY_ENABLED']:
            return {'delay_minutes': 0, 'delay_days': 0}
        rng = self.rng('supply_delay', supply_id)
        value = rng.random()
        if value < self.settings['SUPPLY_INTRADAY_DELAY_PROBABILITY']:
            return {'delay_minutes': rng.randint(*self.settings['SUPPLY_INTRADAY_DELAY_MINUTES']), 'delay_days': 0}
        if value < self.settings['SUPPLY_INTRADAY_DELAY_PROBABILITY'] + self.settings['SUPPLY_DAY_DELAY_PROBABILITY']:
            return {'delay_minutes': 0, 'delay_days': rng.randint(*self.settings['SUPPLY_DELAY_DAYS'])}
        return {'delay_minutes': 0, 'delay_days': 0}

    def absence_dates(self, year, month):#выбор 1–2 дней всего календарного месяца, а не периода запуска
        if not self.settings['VARIABILITY_ENABLED']:
            return []
        rng = self.rng('absence_month', f'{year:04d}-{month:02d}')
        count = rng.randint(*self.settings['ABSENCE_DAYS_PER_MONTH'])
        return sorted(rng.sample(range(1, calendar.monthrange(year, month)[1]+1), count))

    def shift(self, day):#отсутствующий сотрудник и план простоя одной единицы техники
        absent = []
        downtime = None
        if self.settings['VARIABILITY_ENABLED']:
            if day.day in self.absence_dates(day.year, day.month):
                absent = [f"W{self.rng('absent_employee', day.isoformat()).randrange(self.settings['EMPLOYEES'])+1}"]
            rng = self.rng('equipment_downtime', day.isoformat())
            if rng.random() < self.settings['EQUIPMENT_DOWNTIME_PROBABILITY']:
                duration = rng.randint(*self.settings['EQUIPMENT_DOWNTIME_MINUTES'])
                duration = min(duration, self.settings['SHIFT_END_MINUTE'] - self.settings['SHIFT_START_MINUTE'])
                start = rng.randint(self.settings['SHIFT_START_MINUTE'], self.settings['SHIFT_END_MINUTE'] - duration)
                downtime = dict(equipment_id=f"T{rng.randrange(self.settings['EQUIPMENT'])+1}",
                                planned_start_minute=start, duration_minutes=duration,
                                status='planned', actual_start_minute=None, actual_end_minute=None)
        return {'absent_workers': absent, 'downtime': downtime}
