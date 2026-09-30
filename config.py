PALLET_CAPACITY = 40
ZONE_CAPACITY = {"A": 30, "B": 30, "C": 30}
SEED = 42

# Каждый товар хранится отдельно: зона и список паллет с коробками.
INITIAL_STOCK = {
    "SKU-01": {"zone": "A", "pallets": [40] * 7 + [20]},
    "SKU-02": {"zone": "A", "pallets": [40] * 6 + [10]},
    "SKU-03": {"zone": "B", "pallets": [40] * 7 + [30]},
    "SKU-04": {"zone": "B", "pallets": [40] * 6 + [20]},
    "SKU-05": {"zone": "C", "pallets": [40] * 7 + [10]},
    "SKU-06": {"zone": "C", "pallets": [40] * 6 + [30]},
}
