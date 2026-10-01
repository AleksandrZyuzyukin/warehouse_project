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
