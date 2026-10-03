PALLET_CAPACITY = 40
ZONE_CAPACITY = {"A": 30, "B": 30, "C": 30}
SKU_CELL_CAPACITY = 15
REORDER_POINT = 240       # 40% от 15 * 40 коробок
TARGET_STOCK_POSITION = 420  # 70% от 15 * 40 коробок
SUPPLY_LEAD_DAYS = 2
SIMULATION_DAYS = 90
SEED = 42

INITIAL_STOCK = {
    "SKU-01": {"zone": "A", "pallets": [40] * 7 + [20]},
    "SKU-02": {"zone": "A", "pallets": [40] * 6 + [10]},
    "SKU-03": {"zone": "B", "pallets": [40] * 7 + [30]},
    "SKU-04": {"zone": "B", "pallets": [40] * 6 + [20]},
    "SKU-05": {"zone": "C", "pallets": [40] * 7 + [10]},
    "SKU-06": {"zone": "C", "pallets": [40] * 6 + [30]},
}

# Вероятности срока отгрузки: сегодня, завтра, через два дня.
DEADLINE_OFFSETS = (0, 1, 2)
DEADLINE_WEIGHTS = (25, 65, 10)
ORDER_START_MINUTE = 8 * 60 + 30
ORDER_END_MINUTE = 15 * 60

# Смена, ресурсы и время на одну коробку.
SHIFT_START_MINUTE = 9 * 60
SHIFT_END_MINUTE = 17 * 60
EMPLOYEES = 4
EQUIPMENT = 2
RECEIPT_MINUTES = 2
PICK_MINUTES = 3
LOAD_MINUTES = 1
WAITING_CAPACITY = 100
TRUCK_CAPACITY = 80
TRUCK_SCHEDULE = ((11 * 60, 12 * 60 + 30), (15 * 60, 16 * 60 + 30))